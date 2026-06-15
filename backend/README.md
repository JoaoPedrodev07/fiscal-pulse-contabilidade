# Backend — Sistema de Notas Fiscais

API REST em Django para captura e gestão de documentos fiscais eletrônicos (NF-e, NFS-e, CT-e, NFC-e) de uma carteira de clientes contábeis.

---

## Sumário

- [Stack](#stack)
- [Estrutura de arquivos](#estrutura-de-arquivos)
- [Variáveis de ambiente](#variáveis-de-ambiente)
- [Como rodar localmente](#como-rodar-localmente)
- [Banco de dados](#banco-de-dados)
- [Apps e modelos](#apps-e-modelos)
- [API — Endpoints](#api--endpoints)
- [Filtros disponíveis](#filtros-disponíveis)
- [Seed de dados fake](#seed-de-dados-fake)
- [Testes](#testes)
- [Admin Django](#admin-django)
- [O que NÃO está implementado](#o-que-não-está-implementado)

---

## Stack

| Componente | Versão |
|---|---|
| Python | 3.13 |
| Django | 5.2.7 |
| Django REST Framework | 3.14.0 |
| SimpleJWT | 5.3.1 |
| django-filter | latest |
| dj-database-url | 3.0.1 |
| psycopg2-binary | — |
| whitenoise | 6.11.0 |
| gunicorn | — |
| django-storages | — |
| boto3 | — |

**Produção:** Render · Banco: AWS RDS PostgreSQL (us-east-1) · Frontend: Vercel

---

## Estrutura de arquivos

```
backend/
├── manage.py
├── requirements.txt
│
├── Projeto_Notas_Fiscas/       ← módulo de configuração Django
│   ├── settings.py
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
│
├── fiscal/                     ← app do domínio fiscal
│   ├── models.py
│   ├── serializers.py
│   ├── views.py
│   ├── urls.py
│   ├── filters.py
│   ├── admin.py
│   ├── apps.py
│   ├── tests.py                ← 81 testes
│   ├── migrations/
│   └── management/
│       └── commands/
│           └── seed_fiscal.py
│
└── users/                      ← autenticação e perfil de usuário
    ├── models.py
    ├── serializers.py
    ├── views.py
    ├── urls.py
    └── tests.py                ← 12 testes
```

---

## Variáveis de ambiente

| Variável | Obrigatória em prod | Descrição |
|---|---|---|
| `SECRET_KEY` | Sim | Chave secreta do Django |
| `DEBUG` | — | `"True"` para dev; padrão `"True"` se ausente |
| `DATABASE_URL` | Sim | URL do PostgreSQL (ex.: `postgres://user:pass@host/db`) |
| `ALLOWED_HOSTS` | Sim | Hosts separados por vírgula |
| `CORS_ALLOWED_ORIGINS` | Sim | Origins do frontend separadas por vírgula |

Sem `DATABASE_URL`, o Django usa SQLite local (`db.sqlite3`). Em desenvolvimento sem `CORS_ALLOWED_ORIGINS`, o CORS aceita qualquer origem automaticamente (`CORS_ALLOW_ALL_ORIGINS = True`).

---

## Como rodar localmente

```bash
cd backend

python -m venv venv
source venv/Scripts/activate   # Windows
# source venv/bin/activate     # Linux/Mac

pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser   # acesso ao /admin/
python manage.py seed_fiscal       # dados de teste
python manage.py runserver
```

A API fica disponível em `http://localhost:8000/api/`.

---

## Banco de dados

### Tabelas reais no banco

| Tabela | Model | App |
|---|---|---|
| `users_user` | `User` | `users` |
| `fiscal_cliente` | `Cliente` | `fiscal` |
| `fiscal_certificado` | `Certificado` | `fiscal` |
| `fiscal_controlensu` | `ControleNSU` | `fiscal` |
| `fiscal_documento` | `Documento` | `fiscal` |
| `fiscal_xml` | `Xml` | `fiscal` |
| `fiscal_logcaptura` | `LogCaptura` | `fiscal` |

> **`User` ≠ `Cliente`:** O model `User` é autenticação pura (AbstractUser sem campos fiscais). O model `Cliente` é a entidade fiscal — CNPJ, razão social, ativo. Toda FK de "cliente" nos models fiscais aponta para `fiscal_cliente`, **não** para `users_user`.

### Índices criados

- `fiscal_cliente.cnpj` — índice único
- `fiscal_documento.chave` — índice único (deduplicação idempotente)
- `fiscal_documento.competencia` — índice simples
- `doc_cliente_competencia_idx` — índice composto `(cliente_id, competencia)`
- `fiscal_controlensu` — unique_together `(cliente, tipo_documento)`

### Aplicar migrations em PostgreSQL externo

```bash
DATABASE_URL=postgres://user:pass@host:5432/dbname python manage.py migrate
```

---

## Apps e modelos

### `users` — autenticação

#### `User` (AbstractUser puro)

Funcionários do escritório de contabilidade. Não há campos fiscais no `User`.

```
id           BigAutoField   PK
username     CharField      (herdado)
email        EmailField     (herdado)
password     hash           (herdado)
is_staff     BooleanField   True = admin/operador; False = consulta
is_active    BooleanField   (herdado)
date_joined  DateTimeField  (herdado)
last_login   DateTimeField  (herdado)
```

---

### `fiscal` — domínio fiscal

#### `Cliente`

Empresas da carteira do escritório. **Não fazem login** — são gerenciadas pelos `User`s.

```
id            BigAutoField  PK
cnpj          CharField(14) unique  ← só dígitos, sem pontuação
razao_social  CharField(255)
telefone      CharField(15) blank
ativo         BooleanField  default=True
criado_em     DateTimeField auto_now_add
```

#### `Certificado`

```
id            BigAutoField  PK
cliente       FK → fiscal_cliente  on_delete=PROTECT
nome_arquivo  CharField(255)   ← só metadado; o arquivo A1 nunca é armazenado
validade      DateField
ativo         BooleanField     default=True
criado_em     DateTimeField    auto_now_add
```

#### `ControleNSU`

```
id              BigAutoField   PK
cliente         FK → fiscal_cliente  on_delete=CASCADE
tipo_documento  CharField(5)   choices: NFE | CTE | NFSE | NFCE
ultimo_nsu      BigIntegerField  default=0
max_nsu         BigIntegerField  default=0
atualizado_em   DateTimeField    auto_now

unique_together: (cliente, tipo_documento)
```

#### `Documento`

```
id              BigAutoField  PK
cliente         FK → fiscal_cliente  on_delete=PROTECT
chave           CharField(44)  unique + db_index  ← chave de acesso 44 dígitos
tipo_documento  CharField(5)   choices: NFE | CTE | NFSE | NFCE
emitente        CharField(255)
valor           DecimalField(14, 2)
data_emissao    DateField
competencia     CharField(7)   db_index  ← formato "AAAA-MM"
status          CharField(15)  choices: CAPTURADO | MANIFESTADO | COMPLETO
metadados       JSONField      default={}  ← campos variáveis por tipo
criado_em       DateTimeField  auto_now_add

ordering: -data_emissao
index composto: (cliente_id, competencia)
```

#### `Xml`

```
id         BigAutoField  PK
documento  OneToOneField → Documento  on_delete=CASCADE
conteudo   TextField  ← XML completo
criado_em  DateTimeField  auto_now_add
```

> Tabela separada de `Documento` para que listagens não carreguem o texto XML na RAM.

#### `LogCaptura`

```
id              BigAutoField  PK
cliente         FK → fiscal_cliente  on_delete=CASCADE
tipo_documento  CharField(20)
executado_em    DateTimeField  auto_now_add
sucesso         BooleanField
mensagem        TextField  blank=True

ordering: -executado_em
```

---

## API — Endpoints

Todos os endpoints exigem autenticação JWT (exceto `POST /api/token/`).

**Header obrigatório nas requisições autenticadas:**
```
Authorization: Bearer <access_token>
```

---

### Autenticação

| Método | URL | Descrição |
|---|---|---|
| POST | `/api/token/` | Login — retorna `{access, refresh}` |
| POST | `/api/token/refresh/` | Renova o `access` token |

```json
{ "username": "operador1", "password": "senha123" }
```

---

### Usuários — `/api/users/`

| Método | URL | Permissão | Descrição |
|---|---|---|---|
| POST | `/api/users/` | **Staff** | Criar conta — **não é público** |
| GET | `/api/users/` | Staff | Listar todos os usuários |
| GET | `/api/users/{id}/` | Autenticado | Detalhe — não-staff só acessa o próprio |
| DELETE | `/api/users/{id}/` | Staff | Remover usuário |
| GET/PUT/PATCH | `/api/users/me/` | Autenticado | Perfil do usuário logado |

> `POST /api/users/` requer `is_staff=True`. O sistema não tem registro público.

---

### Clientes — `/api/clientes/`

| Método | URL | Permissão | Descrição |
|---|---|---|---|
| GET | `/api/clientes/` | Autenticado | Listar carteira de CNPJs |
| POST | `/api/clientes/` | Staff | Adicionar CNPJ à carteira |
| GET | `/api/clientes/{id}/` | Autenticado | Detalhe |
| PUT/PATCH | `/api/clientes/{id}/` | Staff | Atualizar |
| DELETE | `/api/clientes/{id}/` | Staff | Remover (bloqueado se houver cert ou documento vinculado) |

---

### Certificados — `/api/certificados/`

| Método | URL | Permissão | Descrição |
|---|---|---|---|
| GET | `/api/certificados/` | Autenticado | Listar metadados de certificados |
| POST | `/api/certificados/` | Staff | Criar registro de metadados |
| GET | `/api/certificados/{id}/` | Autenticado | Detalhe |
| PUT/PATCH | `/api/certificados/{id}/` | Staff | Atualizar |
| DELETE | `/api/certificados/{id}/` | Staff | Remover |

> O arquivo A1 (`.pfx`) **nunca** é enviado ou retornado — apenas metadados (`nome_arquivo`, `validade`, `ativo`).

**Resposta de listagem:**
```json
{
  "id": 1,
  "cliente_nome": "Padaria do João Ltda",
  "nome_arquivo": "padaria_joao_2026.pfx",
  "validade": "2026-12-31",
  "ativo": true,
  "criado_em": "2024-01-10T10:00:00Z"
}
```

---

### Documentos — `/api/documentos/`

Somente leitura. A gravação é responsabilidade do worker de captura (Fase 2).

| Método | URL | Descrição |
|---|---|---|
| GET | `/api/documentos/` | Listar com filtros (ver seção Filtros) |
| GET | `/api/documentos/{id}/` | Detalhe do documento + XML embutido |
| GET | `/api/documentos/{id}/xml/` | Baixar XML bruto (`application/xml`) |
| GET | `/api/documentos/exportar_lote/` | Exportar XMLs em ZIP |

#### `GET /api/documentos/{id}/xml/`

- **Content-Type:** `application/xml; charset=utf-8`
- **404** se o documento não tiver XML associado
- **401** se não autenticado

#### `GET /api/documentos/exportar_lote/`

| Parâmetro | Tipo | Obrigatório |
|---|---|---|
| `cliente` | inteiro (ID) | Sim |
| `competencia` | string AAAA-MM | Sim |

- **200** → `application/zip` com um `.xml` por documento
- **400** → se `cliente` ou `competencia` estiver ausente
- ZIP pode ter zero arquivos se não houver documentos com XML na competência

**Resposta de detalhe (`/api/documentos/{id}/`):**
```json
{
  "id": 1,
  "cliente": 3,
  "cliente_nome": "Padaria do João Ltda",
  "chave": "35240112345678000195550010000000011234567890",
  "tipo_documento": "NFE",
  "emitente": "Fornecedor ABC Ltda",
  "valor": "1250.00",
  "data_emissao": "2024-01-10",
  "competencia": "2024-01",
  "status": "COMPLETO",
  "metadados": {},
  "criado_em": "2024-01-10T10:00:00Z",
  "xml": {
    "conteudo": "<?xml version=\"1.0\"?>...",
    "criado_em": "2024-01-10T10:00:00Z"
  }
}
```

`xml` é `null` quando o documento ainda não tem XML associado (status `CAPTURADO`).

Listagens são paginadas — 50 itens por página: `GET /api/documentos/?page=2`

---

### Controles NSU — `/api/controles-nsu/`

Somente leitura. Autenticado.

| Método | URL | Descrição |
|---|---|---|
| GET | `/api/controles-nsu/` | Listar estado NSU por cliente/tipo |
| GET | `/api/controles-nsu/{id}/` | Detalhe |

**Resposta:**
```json
{
  "id": 1,
  "cliente": 3,
  "cliente_nome": "Padaria do João Ltda",
  "tipo_documento": "NFE",
  "ultimo_nsu": 500,
  "max_nsu": 1200,
  "atualizado_em": "2024-01-10T10:00:00Z"
}
```

---

### Logs de captura — `/api/logs-captura/`

Somente leitura. Autenticado.

| Método | URL | Descrição |
|---|---|---|
| GET | `/api/logs-captura/` | Listar logs com `cliente_nome` |
| GET | `/api/logs-captura/{id}/` | Detalhe |

---

## Filtros disponíveis

Em `GET /api/documentos/`:

| Parâmetro | Tipo | Exemplo |
|---|---|---|
| `cliente` | ID inteiro | `?cliente=3` |
| `competencia` | AAAA-MM | `?competencia=2024-01` |
| `tipo_documento` | NFE / CTE / NFSE / NFCE | `?tipo_documento=NFE` |
| `status` | CAPTURADO / MANIFESTADO / COMPLETO | `?status=COMPLETO` |
| `data_emissao_inicio` | AAAA-MM-DD | `?data_emissao_inicio=2024-01-01` |
| `data_emissao_fim` | AAAA-MM-DD | `?data_emissao_fim=2024-03-31` |
| `search` | string | `?search=Fornecedor ABC` — busca em `chave` e `emitente` |
| `page` | inteiro | `?page=2` |

Filtros combinados:
```
GET /api/documentos/?cliente=3&competencia=2024-01&status=COMPLETO
```

---

## Seed de dados fake

```bash
python manage.py seed_fiscal
```

Cria clientes, certificados e documentos com XMLs fake. Idempotente (`get_or_create`).

---

## Testes

```bash
python manage.py test fiscal users --verbosity=2
```

**93 testes, 0 falhas.**

| App | Testes | Classes |
|---|---|---|
| `fiscal` | 81 | ClienteEndpoint, IntegridadeReferencial, IdempotenciaDocumento, ControleNSU, LogCaptura, CertificadoEndpoint, CertificadoVencimento, DocumentoEndpoint, ExportarLote, ValidacaoCompetencia, JWTFluxo |
| `users` | 12 | CriacaoUsuario, MeEndpoint, ListaUsuarios |

**Garantias cobertas pelos testes:**
- JWT obrigatório em todos os endpoints (401 sem token)
- `POST /api/users/` requer staff (401/403 sem privilégio)
- Senha nunca retorna na API
- UNIQUE em `Documento.chave` — `get_or_create` é idempotente
- `unique_together` em `ControleNSU(cliente, tipo_documento)`
- PROTECT impede delete de cliente com cert ou documento vinculado
- CASCADE limpa NSU e logs ao deletar cliente
- Todos os filtros de documento funcionam corretamente
- JWT: login, acesso, refresh, token inválido

---

## Admin Django

Disponível em `/admin/` após `createsuperuser`.

| Model | Busca / Filtros |
|---|---|
| User | username, email |
| Cliente | razao_social, cnpj; filtro por ativo |
| Certificado | cliente, nome_arquivo; filtro por ativo |
| ControleNSU | filtro por tipo_documento |
| Documento | chave, emitente; filtro por tipo, status, competência |
| Xml | chave do documento |
| LogCaptura | filtro por sucesso / tipo_documento |

---

## Decisões de `on_delete`

| Relacionamento | Regra | Motivo |
|---|---|---|
| `Certificado → Cliente` | PROTECT | Não apaga cliente com certificado registrado |
| `ControleNSU → Cliente` | CASCADE | NSU não tem sentido sem o cliente |
| `Documento → Cliente` | PROTECT | Documentos fiscais são auditoria permanente |
| `Xml → Documento` | CASCADE | XML não existe sem o documento pai |
| `LogCaptura → Cliente` | CASCADE | Logs são auxiliares, descartáveis com o cliente |

---

## O que NÃO está implementado

Partes reservadas para a Fase 2 (ver `README.md` na raiz para o roadmap completo):

- **Cofre de certificados A1** — armazenamento criptografado do `.pfx` em repouso (AES-256-GCM)
- **Conector NFS-e ADN** — REST + mTLS contra a API de distribuição nacional
- **Conector NF-e / CT-e** — SOAP + mTLS + XML-DSig contra `NFeDistribuicaoDFe` / `CTeDistribuicaoDFe`
- **Manifestação do destinatário** — evento de Ciência da Operação que libera o XML completo da NF-e
- **Worker Celery** — agendamento e execução assíncrona com disciplina de NSU sequencial e lock distribuído
- **Conector NFC-e** — depende de decisão pendente (SEFAZ estadual por UF ou importação do PDV)
