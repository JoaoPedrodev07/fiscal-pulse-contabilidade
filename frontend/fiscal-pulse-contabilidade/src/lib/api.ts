/**
 * API layer — Fiscal Tracker.
 *
 * The functions below mirror the EXACT Django REST Framework endpoints so that
 * switching from mock to a real backend only requires setting API_BASE_URL and
 * flipping USE_MOCK to false. Each mock function documents the real route it maps to.
 */
import {
  DEMO_CREDENTIALS,
  buildMockXml,
  clientUsers,
  mockCertificados,
  mockDocumentos,
  mockLogs,
  mockNSU,
  mockUsers,
} from "./mock-data";
import type {
  Cliente,
  Certificado,
  ControleNSU,
  Documento,
  DocumentoFilters,
  LogCaptura,
  NovoClienteInput,
  NovoCertificadoInput,
  Paginated,
  UserProfile,
} from "./types";

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
const USE_MOCK = false;

const ACCESS_KEY = "lt_access_token";
const REFRESH_KEY = "lt_refresh_token";
const USER_KEY = "lt_user_id";

export const tokenStore = {
  get access() {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(ACCESS_KEY);
  },
  get refresh() {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(REFRESH_KEY);
  },
  get userId() {
    if (typeof window === "undefined") return null;
    const raw = localStorage.getItem(USER_KEY);
    return raw ? Number(raw) : null;
  },
  set(access: string, refresh: string, userId: number) {
    localStorage.setItem(ACCESS_KEY, access);
    localStorage.setItem(REFRESH_KEY, refresh);
    localStorage.setItem(USER_KEY, String(userId));
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(USER_KEY);
  },
};

const delay = (ms = 350) => new Promise((r) => setTimeout(r, ms));

// In-memory mutable copies so CREATE operations work in mock mode.
let users: UserProfile[] = [...mockUsers];
let certificados: Certificado[] = [...mockCertificados];

function authHeaders(): HeadersInit {
  const token = tokenStore.access;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...authHeaders(), ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = `Erro ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") {
        detail = body.detail;
      } else {
        const firstField = Object.values(body).flat()[0];
        if (typeof firstField === "string") detail = firstField;
      }
    } catch {}
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

// ----------------------------- AUTH -----------------------------
// POST /api/token/
// POST /api/token/
export async function login(username: string, password: string) {
  if (USE_MOCK) {
    await delay();
    const cred = DEMO_CREDENTIALS[username.toLowerCase()];
    if (!cred || cred.password !== password) {
      throw new Error("Usuário ou senha inválidos.");
    }
    const access = `mock-access-${cred.userId}-${Date.now()}`;
    const refresh = `mock-refresh-${cred.userId}`;
    tokenStore.set(access, refresh, cred.userId);
    return { access, refresh };
  }

  // Caminho real (Sem MOCK)
  const data = await http<{ access: string; refresh: string }>("/api/token/", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });

  // Salva o token localmente
  tokenStore.set(data.access, data.refresh, 0); 

  return data;
} // <--- ESSA CHAVE AQUI É A QUE ESTAVA FALTANDO E QUEBROU TUDO!

// GET /api/users/me/
export async function getMe(): Promise<UserProfile> {
  if (USE_MOCK) {
    await delay(150);
    const id = tokenStore.userId;
    const user = users.find((u) => u.id === id);
    if (!user) throw new Error("Sessão expirada.");
    return user;
  }
  return http<UserProfile>("/api/users/me/");
}

// ----------------------------- CLIENTES -----------------------------

// GET /api/clientes/
export async function listClientes(): Promise<Cliente[]> {
  if (USE_MOCK) {
    await delay();
    // Mock: retorna usuários não-staff como clientes (compatibilidade com mock-data)
    return users.filter((u) => !u.is_staff).map((u: any) => ({
      id: u.id,
      cnpj: u.cnpj ?? "",
      razao_social: u.razao_social ?? u.username,
      telefone: u.telefone,
      ativo: true,
    }));
  }

  const data = await http<any>("/api/clientes/");
  return data && typeof data === "object" && "results" in data
    ? (data.results as Cliente[])
    : (data as Cliente[]);
}

// POST /api/clientes/
export async function createCliente(input: NovoClienteInput): Promise<Cliente> {
  if (USE_MOCK) {
    await delay();
    const novo: Cliente = {
      id: Math.max(...users.map((u) => u.id)) + 1,
      cnpj: input.cnpj,
      razao_social: input.razao_social,
      telefone: input.telefone,
      ativo: true,
    };
    return novo;
  }
  return http<Cliente>("/api/clientes/", { method: "POST", body: JSON.stringify(input) });
}

// ----------------------------- CERTIFICADOS -----------------------------
// GET /api/certificados/
// GET /api/certificados/
export async function listCertificados(): Promise<Certificado[]> {
  if (USE_MOCK) {
    await delay();
    const me = users.find((u) => u.id === tokenStore.userId);
    if (me && !me.is_staff) return certificados.filter((c) => c.cliente === me.id);
    return certificados;
  }
  
  // Captura a resposta do Django que vem encapsulada em "Paginated"
  const data = await http<Paginated<Certificado>>("/api/certificados/");
  
  // Se o Django retornar a estrutura paginada com .results, extrai o array.
  // Caso contrário, se o Django já estiver mandando uma lista pura, usa ela.
  return data && typeof data === "object" && "results" in data
    ? (data.results as Certificado[])
    : (data as unknown as Certificado[]);
}

// POST /api/certificados/  (multipart/form-data)
export async function createCertificado(input: NovoCertificadoInput): Promise<Certificado> {
  if (USE_MOCK) {
    await delay(600);
    const novo: Certificado = {
      id: Math.max(0, ...certificados.map((c) => c.id)) + 1,
      cliente: input.cliente,
      cliente_nome: `Cliente #${input.cliente}`,
      nome_arquivo: input.arquivo.name,
      validade: new Date(Date.now() + 365 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10),
      ativo: true,
    };
    certificados = [novo, ...certificados.filter((c) => c.cliente !== input.cliente)];
    return novo;
  }
  // Não setar Content-Type — o browser insere o boundary do multipart automaticamente
  const form = new FormData();
  form.append("cliente", String(input.cliente));
  form.append("arquivo", input.arquivo);
  form.append("senha", input.senha);
  const res = await fetch(`${API_BASE_URL}/api/certificados/`, {
    method: "POST",
    headers: { ...authHeaders() },
    body: form,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const msg =
      body.detail ||
      body.arquivo?.[0] ||
      body.senha?.[0] ||
      body.non_field_errors?.[0] ||
      `Erro ${res.status}`;
    throw new Error(msg);
  }
  return res.json();
}

// ----------------------------- NSU -----------------------------
// GET /api/controles-nsu/
export async function listNSU(): Promise<ControleNSU[]> {
  if (USE_MOCK) {
    await delay();
    const me = users.find((u) => u.id === tokenStore.userId);
    if (me && !me.is_staff) return mockNSU.filter((n) => n.cliente === me.id);
    return mockNSU;
  }
  const data = await http<any>("/api/controles-nsu/");
  return data && typeof data === "object" && "results" in data
    ? (data.results as ControleNSU[])
    : (data as ControleNSU[]);
}

// ----------------------------- LOGS -----------------------------
// ----------------------------- LOGS -----------------------------
export async function listLogs(): Promise<LogCaptura[]> {
  if (USE_MOCK) {
    await delay();
    const me = users.find((u) => u.id === tokenStore.userId);
    if (me && !me.is_staff) return mockLogs.filter((l) => l.cliente === me.id);
    return mockLogs;
  }
  
  const data = await http<any>("/api/logs-captura/");
  
  // Se o Django retornar envelopado em paginação (com .results), extrai a lista real
  if (data && typeof data === "object" && "results" in data) {
    return data.results as LogCaptura[];
  }
  
  return Array.isArray(data) ? data : [];
}

// ----------------------------- DOCUMENTOS -----------------------------
// GET /api/documentos/?cliente=..&competencia=..&tipo_documento=..&status=..&data_emissao_inicio=..&data_emissao_fim=..
export async function listDocumentos(filters: DocumentoFilters): Promise<Paginated<Documento>> {
  if (USE_MOCK) {
    await delay();
    const me = users.find((u) => u.id === tokenStore.userId);
    let rows = [...mockDocumentos];
    if (me && !me.is_staff) rows = rows.filter((d) => d.cliente === me.id);
    if (filters.cliente) rows = rows.filter((d) => d.cliente === Number(filters.cliente));
    if (filters.competencia) rows = rows.filter((d) => d.competencia === filters.competencia);
    if (filters.tipo_documento)
      rows = rows.filter((d) => d.tipo_documento === filters.tipo_documento);
    if (filters.status) rows = rows.filter((d) => d.status === filters.status);
    if (filters.data_emissao_inicio)
      rows = rows.filter((d) => d.data_emissao >= filters.data_emissao_inicio!);
    if (filters.data_emissao_fim)
      rows = rows.filter((d) => d.data_emissao <= filters.data_emissao_fim!);

    const pageSize = filters.page_size ?? 50;
    const page = filters.page ?? 1;
    const start = (page - 1) * pageSize;
    const results = rows.slice(start, start + pageSize);
    return { count: rows.length, next: null, previous: null, results };
  }
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== "" && v !== null) params.set(k, String(v));
  });
  return http<Paginated<Documento>>(`/api/documentos/?${params.toString()}`);
}

// GET /api/documentos/{id}/xml/
export async function downloadXml(doc: Documento): Promise<void> {
  let content: string;
  if (USE_MOCK) {
    await delay(200);
    content = buildMockXml(doc);
  } else {
    const res = await fetch(`${API_BASE_URL}/api/documentos/${doc.id}/xml/`, {
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error(`Erro ${res.status} ao buscar XML`);
    content = await res.text();
  }
  triggerDownload(new Blob([content], { type: "application/xml" }), `${doc.chave}.xml`);
}

// GET /api/documentos/exportar_lote/?cliente=..&competencia=..
export async function exportarLote(filters: DocumentoFilters): Promise<number> {
  if (USE_MOCK) {
    await delay(900);
    const { results, count } = await listDocumentos({ ...filters, page: 1, page_size: 9999 });
    const manifest = results
      .map((d) => `${d.chave}.xml  ${d.tipo_documento}  R$ ${d.valor.toFixed(2)}`)
      .join("\n");
    const blob = new Blob(
      [`FISCAL TRACKER - EXPORTACAO EM LOTE\nTotal: ${count} documentos\n\n${manifest}`],
      { type: "application/zip" },
    );
    const comp = filters.competencia ?? "todas";
    triggerDownload(blob, `notas_${comp}.zip`);
    return count;
  }
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== "" && v !== null) params.set(k, String(v));
  });
  const res = await fetch(`${API_BASE_URL}/api/documentos/exportar_lote/?${params.toString()}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Erro ${res.status} ao exportar lote`);
  const blob = await res.blob();
  triggerDownload(blob, `notas_${filters.competencia ?? "todas"}.zip`);
  return 0;
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  // target="_blank" impede que mobile navegue pra blob URL na aba atual,
  // o que jogaria o usuário fora do app mostrando "página não carregou"
  a.target = "_blank";
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  // Delay para garantir que o browser iniciou o download antes de revogar a URL
  setTimeout(() => {
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, 1000);
}

export { clientUsers };