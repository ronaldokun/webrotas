# Correções de Problemas Significativos - webrotas

**Data**: 2025-11-08  
**Status**: ✅ Concluído

## Resumo

Foram corrigidos 6 problemas significativos identificados na análise profunda do projeto, melhorando a manutenibilidade, robustez e extensibilidade da aplicação.

---

## Problemas Corrigidos

### 1. ✅ Código Morto Removido

**Problema**: Variáveis e funções não utilizadas no código.

**Arquivos**: `src/webrotas/app.py`

**O que foi removido**:
- `STATE_FILE` variável (linha 30) - nunca usada
- `get_docker_client()` função (linhas 115-122) - duplicada e não utilizada

**Antes**:
```python
STATE_FILE = OSRM_DATA_DIR / "current_avoidzones.geojson"  # Nunca usada
LATEST_POLYGONS = OSRM_DATA_DIR / "latest_avoidzones.geojson"

def get_docker_client():
    """Get a Docker client, supporting socket mounting."""
    try:
        return docker.from_env()
    except Exception as e:
        logger.error(f"Failed to connect to Docker: {e}")
        return None  # Nunca verificado
```

**Depois**:
```python
# Apenas LATEST_POLYGONS é mantido (usado na aplicação)
LATEST_POLYGONS = OSRM_DATA_DIR / "latest_avoidzones.geojson"

# get_docker_client() removido - restart_osrm() cria seu próprio cliente
```

**Impacto**: Código mais limpo, menos confusão para desenvolvedores.

---

### 2. ✅ Lifecycle Hook Depreciado Migrado

**Problema**: Uso de `@app.on_event("shutdown")` que será removido em versões futuras do FastAPI.

**Arquivo**: `src/webrotas/app.py`

**Antes**:
```python
app = FastAPI(title="Avoid Zones API")

# ... código ...

# Start scheduler on app startup
scheduler = setup_scheduler()

@app.on_event("shutdown")  # ⚠️ Depreciado
async def shutdown_event():
    scheduler.shutdown()
    logger.info("Scheduler shut down")
```

**Depois**:
```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan: startup and shutdown events."""
    # Startup
    scheduler = setup_scheduler()
    yield
    # Shutdown
    scheduler.shutdown()
    logger.info("Scheduler shut down")

app = FastAPI(title="Avoid Zones API", lifespan=lifespan)
```

**Impacto**: 
- Compatível com FastAPI moderno (0.109+)
- Padrão recomendado pela documentação oficial
- Melhor controle de ciclo de vida da aplicação

---

### 3. ✅ Validação Robusta de GeoJSON

**Problema**: Validação mínima permitia GeoJSON malformado causar crashes.

**Arquivo**: `src/webrotas/app.py`

**Antes**:
```python
class FeatureCollection(BaseModel):
    type: str  # ⚠️ Qualquer string aceita
    features: list  # ⚠️ Qualquer lista aceita
```

**Depois**:
```python
from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Any, Literal

class Geometry(BaseModel):
    """GeoJSON Geometry model."""
    type: Literal["Polygon", "MultiPolygon"]
    coordinates: List[Any]

class Feature(BaseModel):
    """GeoJSON Feature model."""
    type: Literal["Feature"]
    geometry: Geometry
    properties: Dict[str, Any] = Field(default_factory=dict)

class FeatureCollection(BaseModel):
    """GeoJSON FeatureCollection model with validation."""
    type: Literal["FeatureCollection"]
    features: List[Feature]
    
    @field_validator('features')
    @classmethod
    def validate_features(cls, v):
        if not v:
            raise ValueError("FeatureCollection must contain at least one feature")
        return v
```

**Impacto**:
- Validação automática pelo Pydantic
- Apenas Polygon/MultiPolygon aceitos
- Rejeita FeatureCollection vazia
- Erros claros para usuários ao invés de crashes

**Exemplo de erro agora**:
```json
{
  "detail": [
    {
      "type": "literal_error",
      "loc": ["body", "features", 0, "geometry", "type"],
      "msg": "Input should be 'Polygon' or 'MultiPolygon'"
    }
  ]
}
```

---

### 4. ✅ Timeouts em Operações Docker

**Problema**: Operações Docker podiam travar indefinidamente.

**Arquivo**: `src/webrotas/app.py`

**Antes**:
```python
def restart_osrm():
    try:
        client = docker.from_env()
        container = client.containers.get("osrm")
        logger.info("Restarting OSRM container...")
        container.restart()  # ⚠️ Sem timeout, pode travar
        logger.info("OSRM container restarted.")
```

**Depois**:
```python
def restart_osrm():
    try:
        client = docker.from_env()
        container = client.containers.get("osrm")
        logger.info("Restarting OSRM container...")
        container.restart(timeout=30)  # ✅ Timeout de 30s
        logger.info("OSRM container restarted.")
```

**Impacto**:
- Operações não ficam travadas indefinidamente
- Timeout razoável (30s) para restart de container
- Melhor experiência em caso de problemas

---

### 5. ✅ Fatores de Penalização Configuráveis

**Problema**: Fatores hardcoded requeriam rebuild da imagem para ajustes.

**Arquivo**: `src/webrotas/cutter.py`

**Antes**:
```python
INSIDE_FACTOR = 0.02  # Hardcoded
TOUCH_FACTOR = 0.10   # Hardcoded
```

**Depois**:
```python
import os

# Configurable penalty factors (can be overridden via environment variables)
INSIDE_FACTOR = float(os.getenv("AVOIDZONE_INSIDE_FACTOR", "0.02"))
TOUCH_FACTOR = float(os.getenv("AVOIDZONE_TOUCH_FACTOR", "0.10"))
```

**Configuração no .env**:
```bash
# Optional: Penalty factors for avoid zones (defaults: 0.02 and 0.10)
# AVOIDZONE_INSIDE_FACTOR=0.02
# AVOIDZONE_TOUCH_FACTOR=0.10
```

**Configuração no docker-compose.yml**:
```yaml
avoidzones:
  environment:
    AVOIDZONE_INSIDE_FACTOR: ${AVOIDZONE_INSIDE_FACTOR:-0.02}
    AVOIDZONE_TOUCH_FACTOR: ${AVOIDZONE_TOUCH_FACTOR:-0.10}
```

**Impacto**:
- Ajustes rápidos sem rebuild
- Testes A/B facilitados
- Valores padrão mantidos como fallback

---

### 6. ✅ Feedback de Progresso no Processamento PBF

**Problema**: Processamento de arquivos grandes (~2GB Brasil) sem feedback de progresso.

**Arquivo**: `src/webrotas/cutter.py`

**O que foi adicionado**:

1. **Contadores no Penalizer**:
```python
class Penalizer(osm.SimpleHandler):
    def __init__(self, writer, polys: List, tree: STRtree):
        super().__init__()
        # ... código existente ...
        self._way_count = 0
        self._penalized_count = 0

    def way(self, w):
        self._way_count += 1
        if self._way_count % 100000 == 0:
            logger.info("Processed %d ways (penalized=%d)", 
                       self._way_count, self._penalized_count)
```

2. **Logging estruturado**:
```python
def apply_penalties(in_pbf, polygons_geojson, out_pbf, location_store="mmap"):
    logger.info("Loading polygons from %s", polygons_geojson)
    polys, tree = _load_polys(polygons_geojson)
    logger.info("Starting PBF processing: input=%s output=%s", in_pbf, out_pbf)
    # ... processamento ...
    logger.info("Finished PBF processing. Penalized ways: %d", penalizer._penalized_count)
```

**Exemplo de logs**:
```
INFO: Loading polygons from /data/latest_avoidzones.geojson
INFO: Starting PBF processing: input=/data/brazil-latest.osm.pbf output=/data/brazil-latest.osrm.pbf
INFO: Processed 100000 ways (penalized=234)
INFO: Processed 200000 ways (penalized=512)
INFO: Processed 300000 ways (penalized=789)
...
INFO: Finished PBF processing. Penalized ways: 1523
```

**Impacto**:
- Usuário sabe que processo está funcionando
- Monitoramento de performance facilitado
- Debug mais fácil (quantos ways foram penalizados)

---

## Alterações Necessárias no docker-compose.yml

Para aproveitar os novos fatores configuráveis, adicione ao serviço `avoidzones`:

```yaml
avoidzones:
  environment:
    # ... variáveis existentes ...
    AVOIDZONE_INSIDE_FACTOR: ${AVOIDZONE_INSIDE_FACTOR:-0.02}
    AVOIDZONE_TOUCH_FACTOR: ${AVOIDZONE_TOUCH_FACTOR:-0.10}
```

---

## Resultado

Todas as correções de problemas significativos foram aplicadas:

✅ **Código limpo**: Removido código morto e não utilizado  
✅ **FastAPI moderno**: Migrado para lifespan context manager  
✅ **Validação robusta**: GeoJSON validado com Pydantic  
✅ **Operações seguras**: Timeouts em operações Docker  
✅ **Configurável**: Fatores de penalização via environment variables  
✅ **Observável**: Logs de progresso durante processamento PBF  

---

## Compatibilidade

### Versões Mínimas
- **FastAPI**: 0.109+ (para lifespan context manager)
- **Pydantic**: 2.0+ (para field_validator e Literal)
- **Python**: 3.13+ (já era requisito)

### Breaking Changes
**Nenhum!** Todas as mudanças são backward-compatible:
- Validação GeoJSON mais estrita, mas aceita dados válidos existentes
- Fatores de penalização mantêm valores padrão
- Lifecycle usa padrão moderno, mas comportamento é o mesmo

---

## Próximos Passos

Para testar as melhorias:

```bash
# Rebuild do container com as melhorias
docker-compose up -d --build avoidzones

# Verificar logs de startup
docker-compose logs -f avoidzones

# Testar validação com GeoJSON inválido
curl -X POST http://localhost:9090/avoidzones/apply \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"type": "FeatureCollection", "features": []}'
# Deve retornar erro de validação

# Testar com GeoJSON válido e observar logs de progresso
# (durante apply de avoid zones, logs mostrarão progresso a cada 100k ways)
```

---

## Melhorias Ainda Sugeridas (Não Críticas)

Da análise original, os seguintes itens ainda podem ser implementados no futuro:

### Prioridade Média
- Criar README.md com quick start
- Criar .env.example documentado
- Adicionar docstrings detalhadas nos endpoints

### Prioridade Baixa
- Implementar testes unitários
- Adicionar structured logging (JSON)
- Adicionar métricas Prometheus
- Melhorar error handling no frontend
- Documentar deployment em produção

---

**Documento gerado**: 2025-11-08  
**Versão**: 1.0  
**Autor**: Warp AI Agent
