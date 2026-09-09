FROM 10.6.37.167:30005/688-kj-ai/coli-ai-agi/coli-ai-agi-api:base

ARG ENV=dev
ENV COLI_AI_ENV=${ENV}

WORKDIR /app
ENV CHROME_HEADLESS=True

COPY pyproject.toml uv.lock /app/

RUN uv sync --index-url https://pypi.tuna.tsinghua.edu.cn/simple --refresh

COPY . /app

EXPOSE 8080

CMD ["uv", "run", "python", "-m", "app.main"]
