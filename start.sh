#!/bin/bash

# Проверка наличия .env файла
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        echo "Файл .env не найден. Создаю из примера .env.example..."
        cp .env.example .env
        echo "Пожалуйста, отредактируйте файл .env и добавьте ваши API ключи."
        exit 1
    else
        echo "Не найден ни .env, ни .env.example. Невозможно продолжить."
        exit 1
    fi
fi

# Запуск контейнеров
docker-compose up -d

echo "Grid-бот запущен в фоновом режиме."
echo "Для просмотра логов используйте команду: docker-compose logs -f bot"
echo "Для остановки используйте команду: docker-compose down" 