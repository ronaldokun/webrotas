# Correções de Bugs Críticos - webrotas

**Data**: 2025-11-08  
**Status**: ✅ Concluído

## Bugs Corrigidos

### 1. ✅ Health Check com Porta Incorreta (Dockerfile)
**Problema**: Health check verificava porta 5002, mas aplicação roda na 9090.

**Arquivo**: `Dockerfile` (linha 64)

**Antes**:
```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5002/health').read()" || exit 1
```

**Depois**: Removido (health check já está definido no docker-compose.yml na porta correta)

**Impacto**: Container agora será corretamente marcado como healthy.

---

### 2. ✅ Import Incorreto no Dockerfile
**Problema**: CMD usava `src.webrotas.app:app` ao invés de `webrotas.app:app`.

**Arquivo**: `Dockerfile` (linha 67)

**Antes**:
```dockerfile
CMD ["uvicorn", "src.webrotas.app:app", "--host", "0.0.0.0", "--port", "9090"]
```

**Depois**:
```dockerfile
CMD ["uvicorn", "webrotas.app:app", "--host", "0.0.0.0", "--port", "9090"]
```

**Impacto**: Container agora inicia corretamente sem erro de import.

---

### 3. ✅ Código Morto Removido
**Problema**: Comentários duplicados e código morto no final do Dockerfile.

**Arquivo**: `Dockerfile` (linhas 70-72)

**Antes**:
```dockerfile


# EXPOSE 9090
# CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "5002"]
```

**Depois**: Removido completamente

**Impacto**: Dockerfile mais limpo e sem confusão.

---

### 4. ✅ Referência Incorreta ao CSS
**Problema**: HTML referenciava `style.css`, mas arquivo é `styles.css`.

**Arquivo**: `frontend/index.html` (linha 10)

**Antes**:
```html
<link rel="stylesheet" href="./style.css" />
```

**Depois**:
```html
<link rel="stylesheet" href="./styles.css" />
```

**Impacto**: CSS agora carrega corretamente, interface com estilo adequado.

---

### 5. ✅ Porta Incorreta do Tile Server
**Problema**: Frontend tentava acessar porta 8080, mas docker-compose expõe 8090.

**Arquivo**: `frontend/index.html` (linha 47)

**Antes**:
```javascript
const TILE_URL = 'http://localhost:8080/tile/{z}/{x}/{y}.png';
```

**Depois**:
```javascript
const TILE_URL = 'http://localhost:8090/tile/{z}/{x}/{y}.png';
```

**Impacto**: Tiles do mapa agora carregam corretamente.

---

### 6. ✅ Path do OSRM Profile Incorreto
**Problema**: `.env` usava path absoluto do host ao invés do path do container.

**Arquivo**: `.env` (linha 12)

**Antes**:
```bash
OSRM_PROFILE=/media/ronaldo/Homelab/webrotas/profiles/car_avoid.lua
```

**Depois**:
```bash
OSRM_PROFILE=/profiles/car_avoid.lua
```

**Impacto**: OSRM agora usa o profile correto e funciona em qualquer máquina.

---

## Resultado

Todas as correções críticas foram aplicadas. A aplicação agora deve:

✅ Iniciar sem erros de import  
✅ Health checks funcionando corretamente  
✅ CSS carregando na interface  
✅ Tiles do mapa renderizando  
✅ OSRM usando o profile de avoid zones  
✅ Portável para outras máquinas  

## Próximos Passos

Para verificar se tudo está funcionando:

```bash
# Rebuild do container avoidzones com as correções
docker-compose up -d --build avoidzones

# Verificar logs
docker-compose logs -f avoidzones

# Testar health check
curl http://localhost:9090/health

# Acessar frontend
# Abrir http://localhost:8081 no navegador
```

## Observações

- O frontend ainda usa URLs hardcoded (localhost), o que pode causar problemas em deployments remotos. Isso foi identificado na análise mas não é crítico para funcionamento local.
- Considere implementar as melhorias de prioridade média identificadas na análise profunda quando conveniente.
