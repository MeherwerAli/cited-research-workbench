FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN addgroup --system workbench && adduser --system --ingroup workbench workbench
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
RUN mkdir /data && chown workbench:workbench /data
USER workbench
EXPOSE 8090
HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/healthz', timeout=2)"]
CMD ["uvicorn", "research_workbench.main:app", "--host", "0.0.0.0", "--port", "8090"]
