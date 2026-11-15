Запустите START_BACKEND.bat (запустит сервер FastAPI на порту 8080).
Запустите START_FRONTEND.bat (запустит веб-интерфейс диспетчера на порту 3000).
Откройте в браузере: http://localhost:3000 (веб-панель) или http://localhost:8080/docs (Swagger API).


Способ 2. Запуск через Docker Compose

docker compose up --build
Веб-интерфейс диспетчера: http://localhost:3000
Сервер API: http://localhost:8080
Документация OpenAPI/Swagger: http://localhost:8080/docs
