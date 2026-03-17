.PHONY: install test lint typecheck check run run-debug clean

install:
	pip install -e ".[dev]"

test:
	pytest --cov=src/reviewer --cov-report=term-missing --cov-fail-under=80

lint:
	ruff check src/ tests/
	ruff format --check src/ tests/

typecheck:
	mypy --strict src/

check: lint typecheck test

run:
	uvicorn reviewer.main:create_app --factory --host 0.0.0.0 --port 8000

run-debug:
	LOG_LEVEL=debug uvicorn reviewer.main:create_app --factory --host 0.0.0.0 --port 8000 --reload

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .mypy_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +
	rm -rf dist/ build/ *.egg-info/ htmlcov/ .coverage coverage.xml
