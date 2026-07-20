# Atlas Engine

Engine para el Atlas Prospectivo Territorial-Industrial — análisis CGV, econometría y 34 indicadores territoriales extensible a cualquier país/sector.

## Requisitos

- Python >= 3.11
- Docker (opcional)

## Instalación y ejecución

```bash
pip install .
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

### Variables de entorno

Copiá `.env.example` a `.env` y completá las API keys necesarias:

```bash
cp .env.example .env
```

### Docker

```bash
docker build -t atlas-engine .
docker run -p 8000:8000 --env-file .env atlas-engine
```

## API

La documentación OpenAPI está disponible en `http://localhost:8000/docs`.

## Tests

```bash
pip install ".[dev]"
pytest tests/ -v
```
