.PHONY: up down migrate test lint format synthetic synthetic-smoke features graph ml-smoke train-model train-model-v2

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

graph:
	python scripts/build_graph.py --graph-version graph-v1

ml-smoke:
	python scripts/train_model.py --transactions 20000 --artifact-directory /tmp/aegis-model-smoke

train-model:
	python scripts/train_model.py --evaluate-test

train-model-v2:
	python scripts/train_model.py --config configs/ml/model-v2.yaml --artifact-directory ml/artifacts/model-v2 --evaluate-test
