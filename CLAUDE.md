# atlas-engine

Motor de análisis económico-territorial (FastAPI, análisis CGV, 34
indicadores). Es un fork del repo personal de Fernando (`fergcc/atlas-engine`),
no autoría de la empresa Scientika — este checkout tiene dos remotos:
`origin` → `fergcc/atlas-engine` (el que está trackeado) y `fork` →
`r4v72njvft-star/atlas-engine` (secundario).

## Relación con el orchestrator de Scientika

Investigado (2026-07-23): este repo **no tiene integración técnica conocida**
con `scientika-orchestrator-server` — su `.env.example` solo trae llaves de
fuentes de datos externas (SearchAPI, DeepSeek, INEGI, Banxico, FRED), sin
referencias a `BRIDGE_SHARED_SECRET`, `x-bridge-secret`, `bridge.scientika.mx`,
`/agent/tool`, ni en una búsqueda de código a nivel de la organización
`r4v72njvft-star` en GitHub.

Antes de asumir que un cambio aquí es 100% aislado, corre:

```bash
grep -ri "orchestrator\|bridge_shared_secret\|x-bridge-secret\|skai" .
```

— sobre todo si el cambio toca autenticación, webhooks, o llamadas salientes a
otros servicios de Scientika. Si encuentras algo, actualiza esta nota.
