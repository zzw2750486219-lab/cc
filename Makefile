.PHONY: dev test build up down

dev:
	uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest -v

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down
