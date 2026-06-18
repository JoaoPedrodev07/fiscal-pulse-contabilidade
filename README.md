# Sincronizador Fiscal Inteligente

Sistema de captura e custódia ativa de Documentos Fiscais Eletrônicos (DF-e) para escritórios de contabilidade. Captura automaticamente NF-e, CT-e e NFS-e Nacional diretamente das APIs oficiais da SEFAZ — sem portal, sem extensão de terceiros, sem senha manual.

## O que o sistema resolve

| Dor do cliente | Solução entregue |
|----------------|-----------------|
| Senha digitada nota a nota no baixador atual | A1 no cofre AES-256, usado uma vez em memória por ciclo |
| Captura incompleta (perdas por salto de NSU) | NSU sequencial + endpoint `/reconciliar/` mostra o gap antes do fechamento |
| Cancelamentos ausentes (extratores ignoram eventos) | Loop `distNSU` detecta `procEventoNFe tpEvento=110111` e marca status `CANCELADO` automaticamente |

---

## Arquitetura

[Celery Beat — 4h]
│
├─── SOAP + mTLS ──► NFeDistribuicaoDFe (SEFAZ AN)  ─► NF-e + eventos de cancelamento
├─── SOAP + mTLS ──► CTeDistribuicaoDFe (SEFAZ AN)  ─► CT-e
└─── REST + mTLS ──► ADN/Serpro (NT 008/2026)        ─► NFS-e Nacional
│
[Cofre Fernet AES]  ◄── A1 criptografado em repouso por cliente
│
[PostgreSQL]  ──► XMLs + metadados + controle de NSU + logs
│
[API REST Django]  ──► Dashboard React (Vercel)



**Dois modos de captura NFS-e:**
- Automático: Beat 4h via `GET /contribuintes/DFe/{ultimoNSU}?cnpjConsulta=CNPJ` (ADN, NT 008/2026)
- Fallback cirúrgico: `POST /api/clientes/{id}/capturar-nfse/` com chave de acesso de 44 dígitos (tela React)

---

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Backend | Python 3.12 · Django 5 · Django REST Framework |
| Autenticação | SimpleJWT |
| Worker / agendador | Celery + Celery Beat |
| Broker | Redis |
| Banco | PostgreSQL (AWS RDS em produção) |
| Criptografia do A1 | `cryptography` — Fernet AES-256 |
| Conectores SOAP | `zeep` + `requests` (mTLS) |
| Frontend | React · TanStack Router · Tailwind CSS |
| Deploy | Render (backend + worker) · Vercel (frontend) |

---

## Estrutura de módulos

backend/
├── Projeto_Notas_Fiscas/   # settings, urls, wsgi, celery app
├── users/                  # modelo de usuário + JWT (não alterar sem necessidade)
└── fiscal/
├── models.py            # Cliente, Certificado, ControleNSU, Documento, Xml, Manifestacao, LogCaptura
├── views.py             # ViewSets + actions (capturar, capturar-nfse, reconciliar, exportar_lote)
├── serializers.py
├── filters.py           # DocumentoFilter (cliente, competência, tipo, status, papel_nfse)
├── tasks.py             # capturar_cliente() + executar_recolhimento_lote_nsu() [Beat]
├── conectores/
│   ├── fabrica.py       # ConectorSefaz: SOAP NF-e/CT-e + REST mTLS NFS-e
│   ├── nfe.py           # NFeCapturaService: distNSU + cancelamento automático
│   ├── cte.py           # CTeCapturaService: distNSU
│   ├── nfse.py          # NFSeADNCapturaService: ADN REST NT 008/2026
│   └── manifestacao.py  # Ciência da Operação automática (libera XML completo)
├── services/
│   └── cofre.py         # encrypt_a1() / decrypt_a1() — Fernet
├── migrations/          # 0001→0009 (inclui status CANCELADO e campo papel_nfse)
└── tests/
├── test_endpoints.py          # auth, integridade, filtros, reconciliar, capturar-nfse
├── test_nsu_logic.py          # NF-e/CT-e NSU, _esgotar_fila, cancelamento (_processar_evento)
├── test_nfse_adn.py           # conector ADN, tipoPapel, _deep_find, idempotência
├── test_captura_automatica.py # Beat worker, cofre, LogCaptura
└── test_cofre.py              # encrypt/decrypt roundtrip

frontend/fiscal-pulse-contabilidade/
├── src/routes/
│   ├── _authenticated.dashboard.tsx   # visão geral da carteira
│   ├── _authenticated.carteira.tsx    # clientes + upload de certificado A1
│   ├── _authenticated.documentos.tsx  # listagem com filtros e export ZIP
│   └── _authenticated.captura.tsx     # trigger manual NF-e/CT-e + painel NFS-e direta
└── src/lib/api.ts                     # todas as chamadas à API REST



---

## Modelos principais

### Documento
- `chave` CharField(44) **UNIQUE** — garante idempotência (reexecução não duplica)
- `tipo_documento` — NFE | CTE | NFSE | NFCE
- `status` — CAPTURADO → MANIFESTADO → COMPLETO | CANCELADO
- `papel_nfse` — TOMADOR (despesa) | EMITENTE (receita) — indexado para filtros de balancete
- `competencia` — formato `AAAA-MM`, indexado
- `metadados` — JSONField para dados variáveis

### ControleNSU
- `unique_together = [["cliente", "tipo_documento"]]`
- `ultimo_nsu` / `max_nsu` — controle sequencial, nunca pula NSU

### Xml
- `OneToOne(Documento)` — separado por design; listagens não carregam XML

---

## API REST

Base: `/api/`

### Autenticação
POST /api/token/              → {access, refresh}
POST /api/token/refresh/      → {access}



### Clientes e Certificados
GET|POST   /api/clientes/
GET|PATCH|DELETE /api/clientes/{id}/
POST       /api/clientes/{id}/capturar/         → dispara NF-e+CT-e+NFS-e síncrono
GET|POST   /api/certificados/
POST       /api/certificados/{id}/upload/       → envia PFX para o cofre AES



### Documentos
GET  /api/documentos/                            → lista com filtros
?cliente=&tipo_documento=&competencia=
&status=&papel_nfse=&search=
&data_emissao_inicio=&data_emissao_fim=
GET  /api/documentos/{id}/
GET  /api/documentos/{id}/xml/                  → XML bruto
GET  /api/documentos/reconciliar/?cliente=      → gap NSU por tipo
GET  /api/documentos/exportar_lote/?cliente=&competencia=  → ZIP



### NFS-e fallback
POST /api/clientes/{id}/capturar-nfse/
body: {"chave_acesso": "44 dígitos"}       → varredura NSU até encontrar a chave



### Controle e Logs
GET  /api/controles-nsu/
GET  /api/logs-captura/
GET  /api/manifestacoes/



---

## Variáveis de ambiente

Crie `backend/.env` (nunca commitar):

```env
SECRET_KEY=sua-secret-key-django
DATABASE_URL=postgres://user:pass@host:5432/dbname
REDIS_URL=redis://localhost:6379/0

# Cofre AES — gere com: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
CERT_ENCRYPTION_KEY=chave-fernet-base64

# Homologação SEFAZ (True = ambiente de teste, False = produção)
SEFAZ_HOMOLOGACAO=True

# CORS
FRONTEND_URL=http://localhost:5173
Rodando localmente
Backend

cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
Worker Celery (requer Redis)

# Redis via Docker
docker run -p 6379:6379 redis

# Terminal 2 — worker
celery -A Projeto_Notas_Fiscas worker -l info

# Terminal 3 — beat (agenda a captura a cada 4h)
celery -A Projeto_Notas_Fiscas beat -l info
Frontend

cd frontend/fiscal-pulse-contabilidade
npm install
npm run dev
Testes

cd backend
python manage.py test fiscal --verbosity=2
Subsets úteis:


# NSU + cancelamento
python manage.py test fiscal.tests.test_nsu_logic -v 2

# NFS-e ADN
python manage.py test fiscal.tests.test_nfse_adn -v 2

# Beat worker (sem SEFAZ real)
python manage.py test fiscal.tests.test_captura_automatica -v 2

# Endpoints específicos
python manage.py test fiscal.tests.test_endpoints.ReconciliarEndpointTest -v 2
python manage.py test fiscal.tests.test_endpoints.CapturarNfseDiretaEndpointTest -v 2
Todos os testes usam mocks — nunca chamam a SEFAZ real.

Deploy (Render + Vercel)
O arquivo render.yaml define três serviços:

Serviço	Tipo	Comando
fiscal-pulse-api	Web	gunicorn Projeto_Notas_Fiscas.wsgi
fiscal-pulse-worker	Worker	celery -A Projeto_Notas_Fiscas worker -l info
fiscal-pulse-beat	Worker	celery -A Projeto_Notas_Fiscas beat -l info
Variáveis de ambiente a configurar no painel do Render:

SECRET_KEY, DATABASE_URL, REDIS_URL, CERT_ENCRYPTION_KEY, SEFAZ_HOMOLOGACAO, FRONTEND_URL
Frontend: deploy automático no Vercel a partir da pasta frontend/fiscal-pulse-contabilidade. Definir VITE_API_URL apontando para a URL do Render.

Princípios não negociáveis
Idempotência: UNIQUE na chave de 44 dígitos — reexecução nunca duplica documento
NSU sequencial: nunca pular ou desordenar. Erro dispara "Consumo Indevido" e bloqueia o CNPJ na SEFAZ
Segurança do A1: certificado e senha nunca trafegam em texto limpo, nunca são expostos pela API, sempre em repouso criptografado
Homologação first: todo código usa SEFAZ_HOMOLOGACAO=True (tpAmb=2) por padrão
Status de implementação
Componente	Status
Cofre A1 (Fernet AES)	✅
Conector NF-e (SOAP distNSU + cancelamento)	✅
Conector CT-e (SOAP distNSU)	✅
Conector NFS-e ADN (REST mTLS, NT 008/2026)	✅
Manifestação automática (Ciência da Operação)	✅
Worker Celery Beat (4h, todos os clientes)	✅
Endpoint /reconciliar/ (gap NSU)	✅
Endpoint /capturar-nfse/ (fallback cirúrgico)	✅
Export ZIP por cliente/competência	✅
Dashboard React + filtros + upload A1	✅
NFC-e	⏳ Aguardando decisão: SEFAZ estadual ou PDV do cliente?


---
