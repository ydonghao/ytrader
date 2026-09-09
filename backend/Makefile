.PHONY: install install-dev run test clean format lint

# Install dependencies
install:
	uv sync

# Install development dependencies
install-dev:
	uv sync --extra dev

# Run the application
run:
	python main.py

# Run tests
test:
	python -m pytest tests/

# Clean temporary files
clean:
	rm -rf tmp/
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete

# Format code with black and isort
format:
	black .
	isort .

# Run linting with flake8
lint:
	flake8 .

# Run formatting and linting
check: format lint

# Run tests with coverage
test-cov:
	python -m pytest tests/ --cov=app --cov-report=html --cov-report=term