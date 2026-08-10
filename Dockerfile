FROM python:3.11-slim

# Fuerza UTF-8 en todo el contenedor: sin esto, Python cae en ASCII por
# defecto (locale mínima del contenedor) y falla al procesar tildes/emojis
# en las respuestas del agente (ej. "'ascii' codec can't encode characters").
ENV PYTHONIOENCODING=utf-8
ENV PYTHONUTF8=1
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
