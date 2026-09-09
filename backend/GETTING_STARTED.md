# Getting Started Guide

This guide will help you quickly set up and run the ytrader project.

## Prerequisites

- Python 3.13 or higher
- pip or uv (recommended)

## Quick Setup

1. **Install dependencies**:
   ```bash
   # Using uv (recommended)
   make install-dev

   # Or using pip
   pip install -e ".[dev]"
   ```

2. **Run the application**:
   ```bash
   make run
   ```

   Or directly:
   ```bash
   python main.py
   ```

3. **Access the API**:
   Open your browser and go to `http://localhost:8000/docs` to see the API documentation.

## Testing the API

You can test the file analysis endpoint with a sample file:

```bash
curl -X POST "http://localhost:8000/file/analyze" \
     -H "accept: application/json" \
     -H "Content-Type: multipart/form-data" \
     -F "file=@examples/sample.txt"
```

Or using the output_coordinates parameter:

```bash
curl -X POST "http://localhost:8000/file/analyze" \
     -H "accept: application/json" \
     -H "Content-Type: multipart/form-data" \
     -F "file=@examples/sample.txt" \
     -F "output_coordinates=false"
```

## Development Commands

- `make format` - Format code with Black and isort
- `make lint` - Check code style with flake8
- `make test` - Run tests
- `make test-cov` - Run tests with coverage report

## Project Structure

The project follows a Domain-Driven Design (DDD) architecture:

- `main.py` - Application entry point
- `app/core/` - Core utilities (logging, config, exceptions)
- `app/domain/` - Domain entities and interfaces
- `app/application/` - Business logic and use cases
- `app/infrastructure/` - Technical implementations (parsers, storage)
- `app/interfaces/` - API interfaces

## Need Help?

- Check the API documentation at `http://localhost:8000/docs`
- Run tests to verify everything is working: `make test`