# Fiscal Pulse — Sistema de Gestão de Documentos Fiscais

Plataforma para escritórios de contabilidade capturarem, armazenarem e consultarem documentos fiscais eletrônicos (NF-e, CT-e, NFS-e, NFC-e) de uma carteira de CNPJs.

---

## Deploy

| Serviço | URL |
|---|---|
| **Frontend** | [https://fiscal-pulse-contabilidade-89xn952i0.vercel.app ](https://fiscal-pulse-contabilid-git-fdd209-joao-pedro-devs-projects-pro.vercel.app/login)|
| **API** | https://fiscal-pulse-contabilidade.onrender.com/api/ |
| **Admin Django** | https://fiscal-pulse-contabilidade.onrender.com/admin/ |

---

## Endpoints da API

Base: `https://fiscal-pulse-contabilidade.onrender.com`

### Autenticação (público)

| Método | Endpoint | Descrição |
|---|---|---|
| POST | `/api/token/` | Login — retorna `{access, refresh}` |
| POST | `/api/token/refresh/` | Renova o access token |

```json
// Body POST /api/token/
{ "username": "seu_usuario", "password": "sua_senha" }
```

> Todos os endpoints abaixo exigem `Authorization: Bearer <access_token>`

### Usuários

| Método | Endpoint | Permissão |
|---|---|---|
| POST | `/api/users/` | Staff |
| GET | `/api/users/` | Staff |
| GET/PATCH | `/api/users/me/` | Autenticado |

### Clientes (carteira de CNPJs)

| Método | Endpoint | Permissão |
|---|---|---|
| GET | `/api/clientes/` | Autenticado |
| POST | `/api/clientes/` | Staff |
| GET/PATCH/DELETE | `/api/clientes/{id}/` | Staff |

### Certificados

| Método | Endpoint | Permissão |
|---|---|---|
| GET | `/api/certificados/` | Autenticado |
| POST | `/api/certificados/` | Staff |
| GET/PATCH/DELETE | `/api/certificados/{id}/` | Staff |

### Documentos

| Método | Endpoint | Descrição |
|---|---|---|
| GET | `/api/documentos/` | Listar com filtros |
| GET | `/api/documentos/{id}/` | Detalhe + XML embutido |
| GET | `/api/documentos/{id}/xml/` | Download XML (`application/xml`) |
| GET | `/api/documentos/exportar_lote/?cliente=1&competencia=2024-01` | ZIP com todos os XMLs |

**Filtros disponíveis em `/api/documentos/`:**
```
?cliente=1
?competencia=2024-01
?tipo_documento=NFE          # NFE | CTE | NFSE | NFCE
?status=COMPLETO             # CAPTURADO | MANIFESTADO | COMPLETO
?data_emissao_inicio=2024-01-01
?data_emissao_fim=2024-03-31
?search=Nome do Emitente
?page=2
```

### Controles NSU e Logs

| Método | Endpoint | Descrição |
|---|---|---|
| GET | `/api/controles-nsu/` | Estado do NSU por cliente/tipo |
| GET | `/api/logs-captura/` | Histórico de sincronizações |

---

## Funcionalidades

- **Autenticação JWT** — login seguro com access + refresh token
- **Carteira de Clientes** — gerenciamento de CNPJs com controle de certificado digital
- **Documentos Fiscais** — consulta com filtros por cliente, competência, tipo e status
- **Download de XML** — download individual ou exportação em lote (ZIP) por competência
- **Controle de NSU** — rastreamento do número sequencial por cliente e tipo de documento
- **Logs de Captura** — histórico de sincronizações com status e mensagens
- **Dashboard** — métricas, gráficos e alertas de certificados próximos do vencimento
- **93 testes automatizados** — cobertura de segurança, idempotência e integridade referencial

---

## Stack

| Camada | Tecnologia |
|---|---|
| **Backend** | Python 3.13 · Django 5.2 · Django REST Framework 3.14 · SimpleJWT |
| **Banco de dados** | PostgreSQL (AWS RDS) em produção · SQLite em dev |
| **Frontend** | React 19 · TypeScript · TanStack Router · TanStack Query · Tailwind CSS · shadcn/ui |
| **Deploy backend** | Render (gunicorn + whitenoise) |
| **Deploy frontend** | Vercel (TanStack Start SSR) |

---

## Rodar localmente

### Backend

```bash
cd backend
python -m venv venv
source venv/Scripts/activate      # Windows
# source venv/bin/activate        # Linux/Mac
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_fiscal      # dados de teste
python manage.py runserver
```

### Frontend

```bash
cd frontend/fiscal-pulse-contabilidade
npm install
npm run dev
```

### Testes

```bash
cd backend
python manage.py test fiscal users --verbosity=2
# 93 testes, 0 falhas
```

---

## Variáveis de ambiente

### Backend (Render)

```env
SECRET_KEY=<chave-longa-aleatoria>
DEBUG=False
DATABASE_URL=postgres://user:pass@host:5432/dbname
ALLOWED_HOSTS=fiscal-pulse-contabilidade.onrender.com
CORS_ALLOWED_ORIGINS=https://fiscal-pulse-contabilidade-89xn952i0.vercel.app
```

### Frontend (Vercel)

```env
VITE_API_BASE_URL=https://fiscal-pulse-contabilidade.onrender.com
```

---

## Arquitetura

```
.
├── backend/
│   ├── Projeto_Notas_Fiscas/    ← settings, urls, wsgi
│   ├── fiscal/                  ← modelos fiscais, API, testes
│   │   └── connectors/          ← [Fase 2] NFS-e, NF-e, CT-e
│   └── users/                   ← autenticação JWT
│
└── frontend/
    └── fiscal-pulse-contabilidade/
        └── src/
            ├── routes/          ← login, dashboard, carteira, documentos, captura, certificados
            └── lib/
                ├── api.ts       ← camada de integração com o backend
                └── types.ts     ← contratos de tipo compartilhados
```

### Princípio central: `User ≠ Cliente`

| Entidade | Model | Papel |
|---|---|---|
| `User` | `AbstractUser` puro | Funcionários do escritório — **fazem login** |
| `Cliente` | CNPJ + razão social | Empresas da carteira — **não fazem login** |

Toda FK fiscal aponta para `fiscal_cliente`, nunca para `users_user`.

---

## Garantias de segurança

| Garantia | Como é garantida |
|---|---|
| JWT obrigatório em todos os endpoints | `DEFAULT_PERMISSION_CLASSES: IsAuthenticated` |
| Criação de conta restrita a staff | `IsAdminUser` no `POST /api/users/` |
| Senha nunca retorna na API | `password` ausente do `UserSerializer` |
| Nenhum documento duplicado | `UNIQUE` em `Documento.chave` (44 dígitos) |
| Certificado A1 nunca armazenado | `Certificado` só tem metadados (`nome_arquivo`, `validade`) |
| Delete de cliente bloqueado se tiver documentos | `on_delete=PROTECT` em `Certificado` e `Documento` |

---

## Roadmap — Fase 2 (conectores SEFAZ)

| Bloco | Descrição | Estimativa |
|---|---|---|
| 1 — Cofre A1 | AES-256-GCM para armazenar o `.pfx` em repouso | 6 dias |
| 2 — Worker + NSU | Celery + Redis com lock distribuído e disciplina sequencial de NSU | 8 dias |
| 3 — Conector NFS-e | REST + mTLS contra a API ADN | 10 dias |
| 4 — Conector NF-e / CT-e | SOAP + mTLS + XML-DSig | 23 dias |
| 5 — Manifestação | Evento de Ciência da Operação (prazo 90 dias) | 8 dias |
| 6 — NFC-e | Depende de decisão: SEFAZ estadual ou importação do PDV | 5–30 dias |

> Ordem obrigatória: cofre → worker → conectores → manifestação.
> Sem o A1 criptografado, nenhum conector pode autenticar no mTLS da SEFAZ.
