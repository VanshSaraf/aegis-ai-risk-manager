.PHONY: up down migrate test lint format synthetic synthetic-smoke features

up:
	docker compose up --build

down:
	docker compose down

migrate:
	alembic upgrade head

test:
	pytest

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

synthetic:
	python scripts/generate_synthetic.py --seed 42017 --transactions 10000

synthetic-smoke:
	python scripts/generate_synthetic.py --seed 42017 --transactions 250 --no-export

features:
	python scripts/build_features.py --feature-version features-v1
