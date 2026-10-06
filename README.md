# Automacao LATAM em Python

Automacao com Playwright Python para consultar tarifas da LATAM com base em [voos.csv](/Users/gustavocaloi/Documents/dev/busca-aereo/voos.csv), gravar os resultados em [resultado_voos.csv](/Users/gustavocaloi/Documents/dev/busca-aereo/resultado_voos.csv) e atualizar [resumo_resultado.txt](/Users/gustavocaloi/Documents/dev/busca-aereo/resumo_resultado.txt).

## Saida

Cada execucao adiciona novas linhas no CSV de resultado, sem apagar o historico:

```csv
data_hora_processamento,origem,destino,data_voo,menor_preco
2026-04-18 23:14:25 -0300,SJP,SAO,19/10/2026,238.30
2026-04-18 23:14:25 -0300,SAO,SJP,23/10/2026,235.54
```

## Execucao local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./scripts/executar_processamento_e_resumo.sh
```

Esse script faz as duas etapas:
- processa a consulta na LATAM e adiciona novas linhas em [resultado_voos.csv](/Users/gustavocaloi/Documents/dev/busca-aereo/resultado_voos.csv)
- atualiza o resumo em [resumo_resultado.txt](/Users/gustavocaloi/Documents/dev/busca-aereo/resumo_resultado.txt)

Se quiser rodar cada etapa separadamente:

```bash
python scripts/processar_voos_latam.py
python scripts/resumir_resultado.py
```

Opcoes uteis:

```bash
python scripts/processar_voos_latam.py --headed
python scripts/processar_voos_latam.py --profile-dir /tmp/latam-profile
python scripts/processar_voos_latam.py --browser-channel ''
python scripts/processar_voos_latam.py --use-home-searchbox --headed
```

Por padrao, o processamento consulta direto o endpoint de calendario da LATAM e nao abre a home do site. Use
`--use-home-searchbox` apenas para diagnostico, quando quiser ver o preenchimento do buscador no navegador.

## Docker

Build da imagem:

```bash
docker build -t busca-aereo:latest .
```

Execucao simples em loop de 1 hora:

```bash
mkdir -p ./swarm-data/playwright-profile
cp voos.csv ./swarm-data/voos.csv
docker run --rm \
  -e INTERVAL_SECONDS=3600 \
  -e INPUT_CSV=/data/voos.csv \
  -e OUTPUT_CSV=/data/resultado_voos.csv \
  -e SUMMARY_OUTPUT=/data/resumo_resultado.txt \
  -e PROFILE_DIR=/data/playwright-profile \
  -e PLAYWRIGHT_BROWSER_CHANNEL='' \
  -v "$PWD/swarm-data:/data" \
  busca-aereo:latest
```

## Docker Compose

Prepare o volume local:

```bash
mkdir -p ./swarm-data/playwright-profile
cp voos.csv ./swarm-data/voos.csv
touch ./swarm-data/resultado_voos.csv
touch ./swarm-data/resumo_resultado.txt
```

Suba com:

```bash
docker compose up -d --build
```

Comandos uteis:

```bash
docker compose logs -f
docker compose down
```

## Docker Swarm

O Swarm nao tem agendamento horario nativo. Neste projeto, o servico fica em execucao continua e roda a consulta, espera `3600` segundos e executa novamente.

Prepare um diretorio persistente no host:

```bash
mkdir -p /opt/busca-aereo-data/playwright-profile
cp voos.csv /opt/busca-aereo-data/voos.csv
touch /opt/busca-aereo-data/resultado_voos.csv
touch /opt/busca-aereo-data/resumo_resultado.txt
```

Build e deploy:

```bash
docker build -t busca-aereo:latest .
export BUSCA_AEREO_DATA_DIR=/opt/busca-aereo-data
docker stack deploy -c docker-stack.yml busca-aereo
```

Comandos uteis:

```bash
docker service ls
docker service logs -f busca-aereo_busca-aereo
docker stack rm busca-aereo
```

## Observacoes

- Em container, o projeto usa o Chromium embutido da imagem Playwright por padrao.
- O navegador persistente fica em `/data/playwright-profile` no container.
- O site da LATAM usa protecao anti-bot. Em ambiente containerizado, a chance de bloqueio pode ser maior do que em execucao local.
