# Capta Fiscal

> Sistema de captura, custódia e análise de Documentos Fiscais Eletrônicos para escritórios de contabilidade.
> Captura NF-e, CT-e e NFS-e Nacional direto das APIs oficiais da SEFAZ — sem portal, sem extensão de terceiros.

[![Tests](https://img.shields.io/badge/tests-59%20passing-brightgreen)](backend/fiscal/tests/)
[![Python](https://img.shields.io/badge/python-3.13-blue)](https://www.python.org/)
[![Django](https://img.shields.io/badge/django-5.2-green)](https://djangoproject.com/)

---

## O que o sistema resolve

| Dor do escritório | O que o Capta Fiscal entrega |
|-------------------|------------------------------|
| Baixar nota a nota digitando senha | Certificado A1 no cofre AES-256 — autenticado uma vez por ciclo |
| NSUs pulados, captura incompleta | Controle sequencial + `/reconciliar/` mostra o gap antes do fechamento |
| Cancelamentos invisíveis | Loop `distNSU` detecta `tpEvento=110111` e marca `CANCELADO` automaticamente |
| Planilha mensal feita à mão | `NotaTratada`: parser fiscal + parecer automático por nota + exportação `.xlsx` |
| Retenções divergentes não detectadas | Análise CSRF-bundle e divergência de CSLL/PIS/COFINS — parecer `Válida (DIVERGÊNCIA RETENÇÃO)` |
| Cliente substitui nota sem aviso | Cadeia de substituição propagada automaticamente — `Substituída` com chave da nova nota |

---

## Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│  Celery Beat (4h) — captura paralela por cliente            │
│  ├── SOAP + mTLS → NFeDistribuicaoDFe (SEFAZ AN)  → NF-e   │
│  ├── SOAP + mTLS → CTeDistribuicaoDFe (SEFAZ AN)  → CT-e   │
│  └── REST + mTLS → ADN/Serpro (NT 008/2026)       → NFS-e  │
└─────────────────────┬───────────────────────────────────────┘
                      │ cada item
          ┌───────────▼───────────┐
          │  _persistir_item()    │  parse XML único (sem re-parse)
          │  Documento + Xml      │
          │  NotaTratada (parser) │  parecer, retenções, substituição
          └───────────┬───────────┘
                      │
          ┌───────────▼───────────┐
          │  PostgreSQL           │
          │  + índices compostos  │
          └───────────┬───────────┘
                      │
          ┌───────────▼───────────┐
          │  Django REST API      │  SimpleJWT + Token para integração
          └───────────┬───────────┘
                      │
          ┌───────────▼───────────┐
          │  React (TanStack)     │  Vercel — filtros, relatórios, Excel
          └───────────────────────┘
```

**Dois modos de captura NFS-e:**
- **Automático** — Beat 4h, `GET /contribuintes/DFe/{ultimoNSU}?cnpjConsulta=CNPJ` (ADN NT 008/2026)
- **Cirúrgico** — `POST /api/clientes/{id}/capturar-nfse/` com chave de 44 dígitos via tela React

---

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Backend | Python 3.13 · Django 5.2 · Django REST Framework 3.14 |
| Auth | SimpleJWT (dashboard) · DRF Token (integração externa) |
| Worker | Celery + Celery Beat — grupo paralelo por cliente |
| Broker | Redis |
| Banco | PostgreSQL — índices compostos, JSONB, UNIQUE na chave fiscal |
| Cofre A1 | `cryptography` — Fernet AES-256 |
| SOAP | `zeep` + `requests` mTLS — NF-e e CT-e |
| Excel | `xlsxwriter` `constant_memory=True` — O(1) RAM por linha |
| Frontend | React 19 · TanStack Start · TanStack Router · Tailwind CSS |
| Deploy | Render (API + 2 workers) · Vercel (frontend) |

---

## Estrutura de módulos

```
backend/
├── notas_fiscais/                  # settings, urls, wsgi, celery app
├── users/                          # User + JWT (não alterar sem necessidade)
└── fiscal/
    ├── models.py                   # 9 models: Escritorio, Cliente, Certificado,
    │                               #   ControleNSU, Documento, Xml, LogCaptura,
    │                               #   NotaTratada, LogAuditoriaNSU, Manifestacao
    ├── views.py                    # ViewSets + actions
    ├── views_integracao.py         # ExportarPlanilhaView — Token auth para sistemas externos
    ├── serializers.py
    ├── filters.py                  # DocumentoFilter declarativo
    ├── tasks.py                    # capturar_cliente_task + executar_recolhimento_lote_nsu
    ├── urls.py
    ├── conectores/
    │   ├── fabrica.py              # ConectorSefaz: mTLS session
    │   ├── nfe.py                  # NFeCapturaService: distNSU + cancelamento
    │   ├── cte.py                  # CTeCapturaService: distNSU
    │   ├── nfse.py                 # NFSeADNCapturaService: ADN REST NT 008/2026
    │   └── manifestacao.py         # Ciência da Operação automática
    ├── services/
    │   ├── cofre.py                # encrypt_a1() / decrypt_a1()
    │   └── tratamento_nfse.py      # extrair_dados_nfse() — parser fiscal + parecer
    ├── management/commands/
    │   ├── backfill_nota_tratada.py
    │   └── seed_fiscal.py
    ├── migrations/                 # 0001 → 0018
    └── tests/
        └── test_nota_tratada.py    # 59 testes TDD

frontend/fiscal-pulse-contabilidade/
└── src/
    ├── routes/
    │   ├── _authenticated.dashboard.tsx   # visão geral da carteira
    │   ├── _authenticated.carteira.tsx    # clientes + upload de certificado A1
    │   ├── _authenticated.documentos.tsx  # listagem + filtros + export ZIP
    │   ├── _authenticated.captura.tsx     # trigger manual + painel NFS-e direta
    │   └── _authenticated.relatorios.tsx  # NotaTratada: filtros, tabela, parecer, Excel
    └── lib/
        ├── api.ts                         # chamadas à API + exportarRelatorioNfse()
        └── types.ts                       # NotaTratada, ParecerNfse, etc.
```

---

## Modelos principais

### Documento
| Campo | Tipo | Detalhe |
|-------|------|---------|
| `chave` | CharField(50) UNIQUE | 44 dígitos (NF-e/CT-e) ou 50 (NFS-e) — garante idempotência |
| `tipo_documento` | choices | NFE · CTE · NFSE · NFCE |
| `status` | choices | CAPTURADO · MANIFESTADO · COMPLETO · CANCELADO · SUBSTITUIDO |
| `papel_nfse` | CharField db_index | EMITENTE (receita) · TOMADOR (despesa) |
| `competencia` | CharField(7) db_index | formato `AAAA-MM` |
| `metadados` | JSONField | JSONB — dados variáveis por tipo |

Índices: `(cliente, competencia)`, `(cliente, tipo_documento)`.

### NotaTratada
Criada automaticamente para cada NFS-e persistida. Fonte dos relatórios e exportações.

| Campo | Descrição |
|-------|-----------|
| `parecer` | `Válida` · `Válida (DIVERGÊNCIA RETENÇÃO)` · `Cancelada` · `Substituída` |
| `ret_pis/cofins/csll/irrf/inss` | Retenções desagregadas — deteta bundle CSRF automaticamente |
| `chave_substituta` | Chave da nota que substituiu esta (propagação automática) |
| `emitente_cnpj + data_competencia` | Índice composto para queries de relatório |

### ControleNSU
- `unique_together = [(cliente, tipo_documento)]` — um contador por CNPJ por tipo
- `select_for_update()` garante que Celery paralelo não corra condição de corrida

---

## API REST

Base: `/api/`  
Auth: `Authorization: Bearer <jwt>` (todos os endpoints exceto `/api/token/`)

### Autenticação
```
POST /api/token/              → { access, refresh }
POST /api/token/refresh/      → { access }
```

### Clientes & Certificados
```
GET|POST          /api/clientes/
GET|PATCH|DELETE  /api/clientes/{id}/
POST              /api/clientes/{id}/capturar/         # NF-e + CT-e + NFS-e síncrono
POST              /api/clientes/{id}/capturar-nfse/    # body: { chave_acesso: "44 dígitos" }

GET|POST          /api/certificados/
POST              /api/certificados/{id}/upload/       # envia .pfx para cofre AES
```

### Documentos
```
GET  /api/documentos/          # filtros: cliente, competencia, tipo_documento,
                               #   status, papel_nfse, search, data_emissao_after/before
GET  /api/documentos/{id}/
GET  /api/documentos/{id}/xml/
GET  /api/documentos/reconciliar/?cliente=   # gap NSU — 2 queries (sem N+1)
GET  /api/documentos/exportar_lote/?cliente=&competencia=   # ZIP streaming
```

### Relatórios NFS-e (NotaTratada)
```
GET  /api/notas-tratadas/           # filtros: cliente, emitente_cnpj, data_competencia,
                                    #   parecer, papel_nfse, search
GET  /api/notas-tratadas/{id}/
GET  /api/notas-tratadas/exportar/  # .xlsx xlsxwriter constant_memory — O(1) RAM
```

### Controle & Logs
```
GET  /api/controles-nsu/
GET  /api/logs-captura/
GET  /api/auditoria-nsu/
GET  /api/auditoria-nsu/resumo/
GET  /api/manifestacoes/
```

### Integração externa (Token auth)
```
POST /api/v1/integracao/exportar-planilha/
Authorization: Token <api-key>
Body: { "cnpj": "14 dígitos", "mes": 6, "ano": 2025 }
→ .xlsx com 2 abas: "Notas Fiscais" + "Auditoria de Quebras"
```

---

## Variáveis de ambiente

Crie `backend/.env` (nunca commitar):

```env
SECRET_KEY=sua-secret-key-django
DATABASE_URL=postgresql://user:pass@host:5432/dbname
REDIS_URL=redis://localhost:6379/0

# Cofre AES — gere com:
# python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
CERT_ENCRYPTION_KEY=chave-fernet-base64

# False = produção SEFAZ real | True = homologação (padrão)
SEFAZ_HOMOLOGACAO=True

FRONTEND_URL=http://localhost:5173
```

---

## Como rodar localmente

### Backend

```bash
cd backend
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_fiscal    # dados de teste (opcional)
python manage.py runserver
```

API disponível em `http://localhost:8000/api/`.

### Worker Celery (requer Redis)

```bash
# Redis via Docker
docker run -p 6379:6379 redis

# Terminal 2 — worker (captura paralela por cliente)
celery -A notas_fiscais worker -l info

# Terminal 3 — beat (ciclo a cada 4h)
celery -A notas_fiscais beat -l info
```

### Frontend

```bash
cd frontend/fiscal-pulse-contabilidade
npm install
npm run dev
```

### Backfill NotaTratada (documentos históricos)

```bash
# Processa NFS-e já capturadas sem registro tratado
python manage.py backfill_nota_tratada

# Só um cliente
python manage.py backfill_nota_tratada --cliente 42

# Reprocessa todos (força)
python manage.py backfill_nota_tratada --force
```

---

## Testes

```bash
cd backend
python manage.py test fiscal.tests.test_nota_tratada --keepdb --verbosity=2
```

**59 testes, 0 falhas.** Cobrem:

| Classe | O que verifica |
|--------|---------------|
| `ExtrairDadosNfseTest` | parser XML: campos, CSRF-bundle, tpRetPisCofins, substituição |
| `CalcularParecerTest` | lógica de parecer: Válida, Divergência, Cancelada, Substituída |
| `SalvarNotaTratadaIntegracaoTest` | idempotência, propagação de substituição |
| `BackfillNotaTratadaCommandTest` | comando de backfill: --force, --cliente, XML ausente |
| `NotaTratadaViewSetTest` | listagem, filtros, isolamento multi-tenant, somente-leitura |
| `ExportarExcelJWTTest` | endpoint JWT: 200 xlsx, filtro competência, 401 sem auth |
| `IntegracaoExportarPlanilhaTest` | endpoint Token: payload, validações 400, 2 abas, auditoria de quebras |

Todos os testes usam mocks — **nunca chamam a SEFAZ real**.

---

## Deploy (Render + Vercel)

O arquivo `render.yaml` define três serviços:

| Serviço | Tipo | Comando |
|---------|------|---------|
| `fiscal-pulse-api` | Web | `gunicorn notas_fiscais.wsgi` |
| `fiscal-pulse-worker` | Worker | `celery -A notas_fiscais worker -l info` |
| `fiscal-pulse-beat` | Worker | `celery -A notas_fiscais beat -l info` |

**Variáveis no painel do Render:**
`SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`, `CERT_ENCRYPTION_KEY`, `SEFAZ_HOMOLOGACAO`, `FRONTEND_URL`

**Frontend:** deploy automático no Vercel a partir de `frontend/fiscal-pulse-contabilidade/`.  
Definir `VITE_API_BASE_URL` apontando para a URL do Render.

---

## Princípios não negociáveis

| Regra | Por quê |
|-------|---------|
| **Idempotência:** `UNIQUE` na chave fiscal | Reexecução da captura nunca duplica documento |
| **NSU sequencial:** nunca pular ou desordenar | Erro dispara "Consumo Indevido" e bloqueia o CNPJ na SEFAZ |
| **Segurança do A1:** certificado nunca em texto limpo | Nunca trafega pela API, nunca em repouso sem criptografia |
| **`SEFAZ_HOMOLOGACAO`** | Por padrão `True` (tpAmb=2). Só `False` em decisão explícita |
| **Isolamento multi-tenant:** toda query filtra por `escritorio_id` | Escritório A nunca vê dados do escritório B |

---

## Status de implementação

| Componente | Status |
|-----------|--------|
| Cofre A1 (Fernet AES-256) | ✅ |
| Conector NF-e (SOAP distNSU + cancelamento automático) | ✅ |
| Conector CT-e (SOAP distNSU) | ✅ |
| Conector NFS-e ADN (REST mTLS, NT 008/2026) | ✅ |
| Manifestação automática (Ciência da Operação) | ✅ |
| Worker Celery Beat — captura paralela por cliente | ✅ |
| Endpoint `/reconciliar/` — gap NSU sem N+1 | ✅ |
| Endpoint `/capturar-nfse/` — fallback cirúrgico | ✅ |
| Export ZIP por competência (streaming) | ✅ |
| `NotaTratada` — parser fiscal + parecer + CSRF-bundle | ✅ |
| Relatórios NFS-e — filtros + tabela + parecer badge | ✅ |
| Export Excel xlsxwriter `constant_memory` (O(1) RAM) | ✅ |
| API de integração externa (Token + 2 abas + auditoria) | ✅ |
| Backfill histórico (`backfill_nota_tratada`) | ✅ |
| Dashboard React + filtros + upload A1 | ✅ |
| NFC-e | ⏳ Aguardando definição: SEFAZ estadual por UF ou PDV do cliente |
| Evento de Manifestação (Confirmação/Desconhecimento) | ⏳ |
| Export Excel assíncrono (Celery + presigned URL) | ⏳ planejado para >20k notas/export |
