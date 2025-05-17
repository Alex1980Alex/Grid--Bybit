"""
Тесты для модуля grid.py
"""
import pytest
from grid import calculate_grid, calculate_quantity, is_quantity_valid

class TestGridCalculation:
    """Тесты для функций расчета сеток"""
    
    def test_calculate_grid(self):
        """Тест расчета сетки цен"""
        # Тест равномерной сетки
        low_price = 1000
        high_price = 2000
        num_grids = 5
        
        grid = calculate_grid(low_price, high_price, num_grids)
        
        assert len(grid) == num_grids + 1
        assert grid[0] == low_price
        assert grid[-1] == high_price
        assert grid == [1000, 1200, 1400, 1600, 1800, 2000]
        
        # Тест с близкими ценами
        low_price = 1000
        high_price = 1100
        num_grids = 2
        
        grid = calculate_grid(low_price, high_price, num_grids)
        
        assert len(grid) == num_grids + 1
        assert grid[0] == low_price
        assert grid[-1] == high_price
        assert grid == [1000, 1050, 1100]
        
        # Тест с одинаковыми ценами
        with pytest.raises(ValueError):
            calculate_grid(1000, 1000, 5)
        
        # Тест с некорректными параметрами
        with pytest.raises(ValueError):
            calculate_grid(2000, 1000, 5)  # low_price > high_price
            
        with pytest.raises(ValueError):
            calculate_grid(1000, 2000, 0)  # num_grids <= 0
    
    def test_calculate_quantity(self):
        """Тест расчета количества в зависимости от цены"""
        price = 1000
        base_qty = 0.01
        
        # Фиксированное количество
        qty = calculate_quantity(price, base_qty, is_dynamic=False)
        assert qty == base_qty
        
        # Динамическое количество (base_qty - это сумма в USD)
        qty = calculate_quantity(price, 10, is_dynamic=True)
        assert qty == 10 / price
        
        # Проверка округления
        qty = calculate_quantity(1234.56789, 10, is_dynamic=True)
        assert qty != 10 / 1234.56789  # Должно быть округлено
        
    def test_is_quantity_valid(self):
        """Тест проверки валидности количества"""
        # Валидное количество
        assert is_quantity_valid("BTCUSDT", 0.001) == True
        
        # Невалидное количество (слишком маленькое)
        assert is_quantity_valid("BTCUSDT", 0.0001) == False
        
        # Невалидное количество (отрицательное)
        assert is_quantity_valid("BTCUSDT", -0.001) == False 