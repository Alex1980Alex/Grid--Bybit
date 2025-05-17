FROM python:3.11-slim

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование исходного кода
COPY *.py .
COPY .env.example .env.example

# Создание директории для тестов
COPY tests/ tests/

# Установка переменных окружения
ENV PYTHONUNBUFFERED=1

# Запуск бота
CMD ["python", "runner.py", "--symbol", "${SYMBOL:-BTCUSDT}", "--low", "${LOW:-28000}", "--high", "${HIGH:-32000}", "--grids", "${GRIDS:-20}", "--qty", "${QTY:-0.001}"] 