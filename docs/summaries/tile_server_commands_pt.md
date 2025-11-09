# Comandos - Otimização do Tile Server

## Resumo das Mudanças

Modifiquei `docker-compose.yml` para importar apenas dados do Brasil e persistir os dados importados em volumes Docker.

## Principais Mudanças

### tile_import
- **Symlink do PBF**: `ln -sf /data/brazil-latest.osm.pbf /data/region.osm.pbf`
  - Aponta para o arquivo Brasil existente sem copiá-lo
  
- **osm2pgsql otimizado**: `-C 4096 --slim --drop`
  - `-C 4096`: Cache de 4GB para processamento mais rápido
  - `--slim`: Armazena localizações de nós no banco (usa menos RAM)
  - `--drop`: Remove tabelas intermediárias após importação (economiza ~50% de disco)

- **Threads paralelas**: `THREADS: "4"`
  - Usa 4 threads para importação paralela

### Volumes Persistentes

- **`tiles-db`**: Banco PostgreSQL com dados OSM importados
- **`tiles-cache`**: Cache de tiles renderizados

## Comandos Principais

### Primeira Importação (30-60 min para o Brasil)
```bash
docker-compose up tile_import
docker-compose up -d tile_server
```

### Reiniciar (sem reimportar - rápido!)
```bash
docker-compose restart tile_server
# ou
docker-compose down && docker-compose up -d
```

### Reimportar do Zero
```bash
docker-compose down
docker volume rm webrotas_tiles-db webrotas_tiles-cache
docker-compose up tile_import
docker-compose up -d tile_server
```

### Monitorar Progresso
```bash
# Logs da importação
docker-compose logs -f tile_import

# Tamanho do banco após importação
docker exec -it tile_import du -sh /var/lib/postgresql/15/main
```

### Verificar Banco de Dados
```bash
docker exec -it osmtiles psql -U renderer -d gis -c "SELECT COUNT(*) FROM planet_osm_point;"
```

## Ajustes de Performance

### Menos RAM Disponível (reduzir cache)
```yaml
OSM2PGSQL_EXTRA_ARGS: "-C 2048 --slim --drop"  # Cache de 2GB
```

### Mais RAM Disponível (aumentar cache)
```yaml
OSM2PGSQL_EXTRA_ARGS: "-C 8192 --slim --drop"  # Cache de 8GB
```

### Ajustar Threads
```yaml
THREADS: "2"   # Para CPUs dual-core
THREADS: "8"   # Para CPUs 8+ cores
```

## Estimativas para Brasil

- **Tempo de importação**: 30-60 minutos
- **Tamanho do banco**: ~20-30GB
- **RAM durante importação**: 4-6GB

## Estrutura de Argumentos

### osm2pgsql
```bash
osm2pgsql -d gis --create --slim -G --hstore \
  --number-processes 4 \
  -C 4096 \              # Cache em MB
  --slim \               # Modo slim (menos RAM)
  --drop \               # Remove tabelas temp
  /data/region.osm.pbf
```

Parâmetros importantes:
- `-d gis`: Nome do banco de dados
- `--create`: Cria novas tabelas
- `--slim`: Armazena nós no banco (menos RAM, permite updates)
- `-G`: Usa geometrias do PostGIS (padrão)
- `--hstore`: Armazena tags OSM em hstore
- `--number-processes N`: Usa N processos paralelos
- `-C CACHE`: Cache em MB para processamento
- `--drop`: Remove tabelas intermediárias após importação
