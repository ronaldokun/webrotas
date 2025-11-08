# Análise Profunda - webrotas

## Resumo Executivo

Este documento apresenta uma análise detalhada do projeto webrotas, identificando oportunidades de melhoria, simplificação e boas práticas. O projeto está bem estruturado, mas há áreas que podem ser otimizadas para melhor manutenibilidade, performance e robustez.

---

## 1. Arquitetura e Estrutura

### ✅ Pontos Fortes
- **Separação clara de responsabilidades**: `app.py` (API/orquestração), `cutter.py` (processamento PBF)
- **Uso de Python moderno**: Python 3.13+ com `uv` para gestão de dependências
- **Docker Compose bem organizado**: Serviços isolados e dependências claras
- **Sistema de versionamento**: Histórico completo de configurações de avoid zones

### ⚠️ Áreas de Melhoria

#### 1.1 Estrutura de Módulos
**Problema**: O projeto está organizado como pacote (`src/webrotas/`) mas o Dockerfile ainda referencia caminhos incorretos.

**Evidência**:
```dockerfile
# Linha 67 do Dockerfile
CMD ["uvicorn", "src.webrotas.app:app", "--host", "0.0.0.0", "--port", "9090"]
```

**Recomendação**: Ajustar para usar o módulo instalado:
```dockerfile
CMD ["uvicorn", "webrotas.app:app", "--host", "0.0.0.0", "--port", "9090"]
```

#### 1.2 README.md Vazio
**Problema**: O README.md está completamente vazio, dificultando onboarding de novos desenvolvedores.

**Recomendação**: Criar documentação básica com:
- Visão geral do projeto
- Quick start (comandos básicos)
- Link para WARP.md para detalhes técnicos
- Requisitos do sistema

---

## 2. Código Python - app.py

### 🐛 Bugs e Inconsistências

#### 2.1 Variável Não Utilizada
**Problema**: `STATE_FILE` é definida mas nunca usada (linha 30).

```python
STATE_FILE = OSRM_DATA_DIR / "current_avoidzones.geojson"  # ❌ Nunca usada
```

**Impacto**: Código morto, confusão conceitual (LATEST_POLYGONS vs STATE_FILE).

**Recomendação**: Remover ou consolidar com `LATEST_POLYGONS`.

#### 2.2 Health Check Inconsistente
**Problema**: O Dockerfile verifica porta 5002, mas a aplicação roda na 9090.

```dockerfile
# Linha 64 do Dockerfile
CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5002/health').read()"
```

**Impacto**: Health checks sempre falharão, container pode ser marcado como unhealthy.

**Recomendação**: Corrigir para porta 9090 ou usar curl (já disponível no container).

#### 2.3 Duplicação de Código
**Problema**: `get_docker_client()` (linhas 115-122) retorna cliente mas nunca é usado. `restart_osrm()` cria seu próprio cliente.

```python
def get_docker_client():
    """Get a Docker client, supporting socket mounting."""
    try:
        return docker.from_env()
    except Exception as e:
        logger.error(f"Failed to connect to Docker: {e}")
        return None  # ❌ Nunca é verificado pelos chamadores
```

**Recomendação**: Remover `get_docker_client()` ou refatorar `restart_osrm()` para usá-la.

### 🔒 Segurança

#### 2.4 Token em Plaintext
**Problema**: Token armazenado diretamente em `.env` sem proteção adicional.

```python
AVOIDZONES_TOKEN = os.getenv("AVOIDZONES_TOKEN", "default-token")
```

**Impacto**: Baixo (ambiente controlado), mas não é uma boa prática para produção.

**Recomendação**: 
- Curto prazo: Documentar que o token deve ser forte
- Longo prazo: Considerar uso de secrets do Docker ou vault

#### 2.5 CORS Totalmente Aberto
**Problema**: CORS permite qualquer origem (linha 48).

```python
allow_origins=["*"],  # ❌ Permite qualquer site
```

**Impacto**: Qualquer site pode fazer requests ao API se souber o token.

**Recomendação**: Especificar origens permitidas ou adicionar nota na documentação sobre deployment em produção.

### 🚀 Performance e Robustez

#### 2.6 Falta de Timeout em restart_osrm()
**Problema**: Restart do container pode ficar travado indefinidamente.

```python
container.restart()  # ❌ Sem timeout
```

**Recomendação**: Adicionar timeout:
```python
container.restart(timeout=30)
```

#### 2.7 Download PBF Síncrono
**Problema**: `download_pbf()` é síncrono e bloqueia o event loop durante downloads grandes (linha 140).

```python
subprocess.run([...], timeout=3600)  # ❌ 1 hora bloqueando
```

**Impacto**: Durante cron job às 2 AM, API fica não-responsiva por até 1 hora.

**Recomendação**: Implementar download assíncrono ou marcar endpoint como "maintenance mode".

#### 2.8 Falta de Validação de GeoJSON
**Problema**: Validação mínima de GeoJSON (apenas checa `type`).

```python
if geojson.get("type") != "FeatureCollection":
    raise ValueError("Expected FeatureCollection")
```

**Impacto**: GeoJSON malformado pode causar crashes no `cutter.py`.

**Recomendação**: Adicionar validação de schema usando `pydantic` ou `jsonschema`.

### 📝 Qualidade de Código

#### 2.9 Lifecycle Hook Depreciado
**Problema**: Uso de `@app.on_event("shutdown")` que será removido no FastAPI.

```python
@app.on_event("shutdown")  # ⚠️ Depreciado
async def shutdown_event():
    scheduler.shutdown()
```

**Recomendação**: Migrar para lifespan context manager (FastAPI 0.109+):
```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = setup_scheduler()
    yield
    scheduler.shutdown()
    
app = FastAPI(lifespan=lifespan)
```

#### 2.10 Logging Pouco Estruturado
**Problema**: Logs em formato livre, difícil de parsear para monitoring.

**Recomendação**: Usar structured logging com `structlog` ou JSON formatter.

---

## 3. Código Python - cutter.py

### ✅ Pontos Fortes
- Uso eficiente de STRtree para indexação espacial
- Lógica clara de penalização (inside vs touch)
- Tratamento adequado de erros de geometria

### ⚠️ Áreas de Melhoria

#### 3.1 Hardcoded Constants
**Problema**: Fatores de penalização são constantes globais (linhas 10-11).

```python
INSIDE_FACTOR = 0.02
TOUCH_FACTOR = 0.10
```

**Impacto**: Ajustes requerem rebuild da imagem Docker.

**Recomendação**: Tornar configuráveis via environment variables ou parâmetros de função.

#### 3.2 Falta de Progress Feedback
**Problema**: Processamento de PBF grande (~2GB Brasil) não dá feedback de progresso.

**Impacto**: Usuário não sabe se processo travou ou está progredindo.

**Recomendação**: Adicionar logging periódico (ex: a cada 100k ways processadas).

#### 3.3 Memory Management
**Problema**: `location_store` é hardcoded como "mmap" (linha 84), mas função aceita parâmetro que nunca é usado de forma diferente.

**Recomendação**: 
- Remover parâmetro se sempre usar mmap
- OU documentar quando usar "flex_mem"

---

## 4. Docker e Infraestrutura

### 🐛 Problemas Identificados

#### 4.1 pbf_fetcher Comentado
**Problema**: Serviço `pbf_fetcher` está completamente comentado no docker-compose.yml.

**Impacto**: Dependência manual de PBF já existente no volume.

**Recomendação**: 
- Descomentar e documentar uso inicial
- OU remover completamente se obsoleto (substituído por download no avoidzones)

#### 4.2 Path Inconsistente no .env
**Problema**: `OSRM_PROFILE` usa path absoluto do host, não do container (linha 12 do .env).

```bash
OSRM_PROFILE=/media/ronaldo/Homelab/webrotas/profiles/car_avoid.lua  # ❌ Path do host
```

**Impacto**: Não funcionará em outras máquinas.

**Recomendação**: Usar path do container:
```bash
OSRM_PROFILE=/profiles/car_avoid.lua
```

#### 4.3 Comentários Duplicados no Dockerfile
**Problema**: Linhas 70-72 do Dockerfile têm comandos comentados duplicando a lógica ativa.

```dockerfile
# EXPOSE 9090
# CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "5002"]
```

**Recomendação**: Remover código morto.

#### 4.4 Healthcheck Duplicado
**Problema**: Health check definido tanto no Dockerfile quanto no docker-compose.yml.

**Impacto**: Configuração do docker-compose sobrescreve, mas causa confusão.

**Recomendação**: Remover do Dockerfile, manter apenas no docker-compose.yml.

#### 4.5 Permissões do Docker Socket
**Problema**: Container avoidzones tem acesso ao Docker socket.

```yaml
- /var/run/docker.sock:/var/run/docker.sock:ro
```

**Impacto**: Risco de segurança se container for comprometido (pode controlar host Docker).

**Recomendação**: 
- Curto prazo: Documentar o risco
- Longo prazo: Implementar proxy Docker com permissões limitadas

### 📦 Otimizações

#### 4.6 Imagem OSRM Desatualizada
**Problema**: Comentário no WARP.md menciona versão 6.0.0, mas docker-compose usa `latest`.

```yaml
image: ghcr.io/project-osrm/osrm-backend:latest  # ⚠️ Não determinístico
```

**Recomendação**: Pin específico para reproducibilidade:
```yaml
image: ghcr.io/project-osrm/osrm-backend:v5.28.0
```

#### 4.7 Build Context Desnecessário
**Problema**: Dockerfile copia `README.md` vazio (linha 26).

**Impacto**: Pequeno, mas desnecessário.

**Recomendação**: Remover da cópia ou popular README primeiro.

---

## 5. Frontend

### 🐛 Problemas

#### 5.1 Hardcoded URLs
**Problema**: URLs de serviços são hardcoded (linhas 47-49).

```javascript
const TILE_URL = 'http://localhost:8080/tile/{z}/{x}/{y}.png';
const OSRM_URL = 'http://localhost:5000';
const API_URL = 'http://localhost:9090';
```

**Impacto**: Não funciona em deployments remotos ou com portas diferentes.

**Recomendação**: Usar environment variables ou path relativo.

#### 5.2 Porta Incorreta do Tile Server
**Problema**: Frontend tenta acessar porta 8080, mas docker-compose expõe 8090.

```javascript
const TILE_URL = 'http://localhost:8080/tile/{z}/{x}/{y}.png';  // ❌
```

```yaml
# docker-compose.yml linha 71
ports:
  - "8090:80"
```

**Impacto**: Tiles não carregarão.

**Recomendação**: Alinhar portas (usar 8090 no frontend).

#### 5.3 Falta de Error Handling
**Problema**: Muitos `await fetch()` sem try-catch adequado.

**Impacto**: Erros de rede resultam em UX ruim (página trava).

**Recomendação**: Adicionar try-catch e feedback visual.

#### 5.4 Nome do Arquivo CSS Incorreto
**Problema**: HTML referencia `style.css` (linha 10), arquivo é `styles.css`.

```html
<link rel="stylesheet" href="./style.css" />  <!-- ❌ -->
```

**Impacto**: CSS não carrega, página sem estilo.

**Recomendação**: Corrigir para `styles.css`.

### 🎨 Melhorias de UX

#### 5.5 Sem Feedback de Loading
**Problema**: Operações longas (Apply, Route) não mostram loading spinner.

**Recomendação**: Adicionar indicadores visuais de progresso.

#### 5.6 Token Não Persistido
**Problema**: Token precisa ser inserido a cada reload da página.

**Recomendação**: Salvar em localStorage (com disclaimer de segurança).

---

## 6. Testes

### ❌ Crítico: Ausência Total de Testes

**Problema**: Nenhum teste automatizado no repositório.

**Impacto**: 
- Regressões não são detectadas
- Refatoração é arriscada
- Qualidade não é garantida

**Recomendação**: Implementar testes em fases:

#### Fase 1: Testes Unitários
```python
# tests/test_cutter.py
def test_load_polys_valid_geojson():
    # Testa parsing de GeoJSON válido
    
def test_penalizer_inside_polygon():
    # Testa fator de penalização para way completamente dentro
    
def test_penalizer_touching_polygon():
    # Testa fator de penalização para way tocando borda
```

#### Fase 2: Testes de Integração
```python
# tests/test_api.py
def test_apply_avoidzones_endpoint():
    # Testa endpoint completo
    
def test_history_endpoint_auth():
    # Testa autenticação
```

#### Fase 3: Testes E2E
- Usar `pytest-docker` para testar com containers reais
- Verificar fluxo completo: upload → process → restart → routing

---

## 7. Documentação

### ✅ Pontos Fortes
- WARP.md muito completo e detalhado
- Documentação inline em comentários do código

### ⚠️ Gaps

#### 7.1 Ausência de API Documentation
**Problema**: Endpoints não têm docstrings detalhadas.

**Recomendação**: Aproveitar auto-docs do FastAPI:
```python
@app.post("/avoidzones/apply", response_model=ApplyResponse)
async def apply_avoidzones(
    fc: FeatureCollection, 
    token: str = Depends(verify_token)
):
    """
    Apply avoid zones and rebuild OSRM routing engine.
    
    Args:
        fc: GeoJSON FeatureCollection with Polygon/MultiPolygon features
        
    Returns:
        ApplyResponse with status and timestamped filename
        
    Raises:
        HTTPException: 400 if invalid GeoJSON, 500 if processing fails
        
    Example:
        POST /avoidzones/apply
        Authorization: Bearer <token>
        {
          "type": "FeatureCollection",
          "features": [...]
        }
    """
```

#### 7.2 Environment Variables Não Documentadas
**Problema**: `.env` não tem comentários explicando cada variável.

**Recomendação**: Adicionar `.env.example` com documentação completa.

#### 7.3 Deployment Guide Ausente
**Problema**: Não há guia de como fazer deploy em produção.

**Recomendação**: Adicionar `docs/DEPLOYMENT.md` cobrindo:
- Requisitos de hardware
- Configuração de firewall
- Backup do volume de dados
- Monitoramento e logs

---

## 8. Observabilidade

### ❌ Ausente: Metrics e Monitoring

**Problema**: Nenhuma métrica ou telemetria.

**Recomendação**: Adicionar:
- Prometheus endpoint (`prometheus-fastapi-instrumentator`)
- Métricas customizadas:
  - Tempo de processamento de PBF
  - Número de ways penalizadas
  - Tamanho de arquivos históricos
  - Frequência de uso de cada endpoint

---

## 9. Simplificações Possíveis

### 9.1 Remover Tile Server (Opcional)
**Análise**: O tile server consome ~4GB de RAM e é independente da funcionalidade core.

**Opção 1 - Usar Tile Provider Externo**:
```javascript
const TILE_URL = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
```

**Prós**: 
- Reduz complexidade Docker
- Economiza recursos
- Menos manutenção

**Contras**: 
- Dependência externa
- Possíveis limites de rate

**Recomendação**: Manter atual, mas documentar opção de tile provider externo.

### 9.2 Consolidar Serviços
**Análise**: `tile_import` e `tile_server` poderiam ser um único serviço com entrypoint script.

**Impacto**: Simplifica docker-compose, mas complica inicialização.

**Recomendação**: Manter separado (mais claro).

### 9.3 Remover Scheduler
**Análise**: Cron job às 2 AM poderia ser substituído por cronjob do sistema operacional.

**Prós**:
- Remove dependência (apscheduler)
- Mais controle sobre execução

**Contras**:
- Menos portável
- Requer configuração externa

**Recomendação**: Manter atual (mais self-contained).

---

## 10. Plano de Ação Priorizado

### 🔴 Prioridade Alta (Bugs)
1. **Corrigir porta do health check** no Dockerfile (5002 → 9090)
2. **Corrigir porta do tile server** no frontend (8080 → 8090)
3. **Corrigir nome do arquivo CSS** no HTML (style.css → styles.css)
4. **Corrigir OSRM_PROFILE** no .env (usar path do container)
5. **Corrigir import no Dockerfile** (src.webrotas.app → webrotas.app)

### 🟡 Prioridade Média (Melhorias)
6. **Remover código morto**: STATE_FILE, get_docker_client(), comentários
7. **Migrar lifecycle hooks** para lifespan context
8. **Adicionar validação de GeoJSON** com schema
9. **Adicionar timeouts** em restart_osrm() e outras operações Docker
10. **Criar README.md** com quick start
11. **Criar .env.example** documentado
12. **Tornar fatores de penalização configuráveis**

### 🟢 Prioridade Baixa (Qualidade)
13. **Implementar testes unitários** (fase 1)
14. **Adicionar docstrings** nos endpoints
15. **Implementar structured logging**
16. **Adicionar métricas Prometheus**
17. **Melhorar error handling** no frontend
18. **Adicionar progress feedback** no processamento PBF
19. **Documentar deployment** em produção

---

## 11. Estimativa de Esforço

| Tarefa | Esforço | Impacto | Risco |
|--------|---------|---------|-------|
| Correção de bugs (itens 1-5) | 2h | Alto | Baixo |
| Remoção de código morto (6) | 1h | Médio | Baixo |
| Migração lifecycle (7) | 1h | Médio | Baixo |
| Validação GeoJSON (8) | 2h | Alto | Baixo |
| Timeouts (9) | 1h | Médio | Baixo |
| Documentação básica (10-11) | 3h | Alto | Nenhum |
| Testes unitários (13) | 8h | Alto | Médio |
| Metrics (16) | 4h | Médio | Baixo |
| **Total Prioridade Alta+Média** | **10h** | | |
| **Total Completo** | **22h** | | |

---

## 12. Conclusão

O projeto **webrotas** demonstra uma arquitetura sólida e funcional, com boas práticas em muitas áreas. As principais oportunidades de melhoria estão em:

1. **Correção de bugs críticos** que impedem funcionamento correto
2. **Remoção de código morto** para melhor manutenibilidade
3. **Adição de testes** para garantir qualidade
4. **Melhoria de documentação** para facilitar onboarding

A maioria das melhorias são de baixo risco e podem ser implementadas incrementalmente, sem necessidade de refatoração massiva.

### Próximos Passos Recomendados

1. **Sprint 1 (1 dia)**: Corrigir todos os bugs de prioridade alta
2. **Sprint 2 (1 dia)**: Implementar melhorias de prioridade média
3. **Sprint 3 (2 dias)**: Adicionar testes e métricas básicas
4. **Sprint 4 (ongoing)**: Melhorias contínuas baseadas em uso real

---

**Documento gerado**: 2025-11-08  
**Versão**: 1.0  
**Autor**: Warp AI Agent
