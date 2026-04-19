# Automacao LATAM em Python

Automacao com Playwright Python para abrir a home da LATAM Brasil e preencher o campo `De` com `SJP`.

## Como usar

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/preencher_latam.py
```

## Opcoes uteis

```bash
python scripts/preencher_latam.py --from-airport SJP
python scripts/preencher_latam.py --close
python scripts/preencher_latam.py --headless
```

## Observacoes

- O script abre a pagina `https://www.latamairlines.com/br/pt`.
- Por padrao, ele usa o Google Chrome instalado na maquina e deixa a janela aberta no final.
- O site da LATAM usa protecao anti-bot. Se aparecer `Access Denied`, rode em modo visivel e, se necessario, use a mesma rede/perfil que voce usa normalmente no navegador.
