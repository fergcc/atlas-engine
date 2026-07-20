"""Clientes HTTP por fuente pública (INEGI, Banxico, FRED, BEA, BLS).

Cada módulo expone funciones que llaman a la API real correspondiente leyendo
la credencial desde una variable de entorno (vía `python-dotenv`). Mientras el
usuario no haya conseguido credenciales reales, estas funciones deben fallar
explícitamente:

- `MissingCredentialError` si la variable de entorno no está definida.
- `SourceUnavailableError` si la fuente responde con error/timeout/payload
  inválido tras los reintentos con backoff (`tenacity`).

Ninguna función de este paquete devuelve datos inventados disfrazados de
reales. Para desarrollar/probar el frontend sin credenciales, usar
`pipeline.mock.generate_mock_data`.
"""
