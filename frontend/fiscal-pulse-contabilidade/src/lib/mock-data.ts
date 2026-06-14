import type {
  Certificado,
  Cliente,
  ControleNSU,
  Documento,
  LogCaptura,
  StatusDocumento,
  TipoDocumento,
  UserProfile,
} from "./types";

// Demo credentials (mock auth)
export const DEMO_CREDENTIALS: Record<string, { password: string; userId: number }> = {
  contabilidade: { password: "123456", userId: 1 },
  lasanha: { password: "123456", userId: 2 },
};

export const mockUsers: UserProfile[] = [
  { id: 1, username: "contabilidade", email: "contato@escritoriofiscal.com.br", is_staff: true, is_active: true },
  { id: 2, username: "operador",      email: "operador@escritoriofiscal.com.br", is_staff: false, is_active: true },
];

export const mockClientes: Cliente[] = [
  { id: 2,  cnpj: "98765432000121", razao_social: "Lasanha da Nonna Comercio de Alimentos LTDA", telefone: "(11) 99876-5432", ativo: true },
  { id: 3,  cnpj: "45123789000155", razao_social: "Padaria Doze de Maio EIRELI",                 telefone: "(11) 3344-1122", ativo: true },
  { id: 4,  cnpj: "33987654000108", razao_social: "Rotas Log Transportes S.A.",                  telefone: "(19) 3251-7700", ativo: true },
  { id: 5,  cnpj: "21555444000133", razao_social: "Tech Store Eletronicos LTDA",                  telefone: "(11) 2020-3030", ativo: false },
];

// clientUsers agora retorna Clientes (CNPJs da carteira), não Users
export const clientUsers: Cliente[] = mockClientes;

const today = new Date();
function isoDaysFromNow(days: number) {
  const d = new Date(today);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export const mockCertificados: Certificado[] = [
  {
    id: 1,
    cliente: 2,
    cliente_nome: "Lasanha da Nonna Comércio de Alimentos LTDA",
    nome_arquivo: "lasanha_a1_2025.pfx",
    validade: isoDaysFromNow(18),
    ativo: true,
  },
  {
    id: 2,
    cliente: 3,
    cliente_nome: "Padaria Doze de Maio EIRELI",
    nome_arquivo: "padaria_doze_a1.pfx",
    validade: isoDaysFromNow(212),
    ativo: true,
  },
  {
    id: 3,
    cliente: 4,
    cliente_nome: "Rotas Log Transportes S.A.",
    nome_arquivo: "rotaslog_certificado.pfx",
    validade: isoDaysFromNow(-7),
    ativo: false,
  },
  {
    id: 4,
    cliente: 5,
    cliente_nome: "Tech Store Eletrônicos LTDA",
    nome_arquivo: "techstore_a1.pfx",
    validade: isoDaysFromNow(95),
    ativo: true,
  },
];

export const mockNSU: ControleNSU[] = [
  { id: 1, cliente: 2, cliente_nome: "Lasanha da Nonna Comércio de Alimentos LTDA", tipo_documento: "NFE", ultimo_nsu: 154820, max_nsu: 154820, atualizado_em: isoDaysFromNow(0) + "T08:12:00Z" },
  { id: 2, cliente: 3, cliente_nome: "Padaria Doze de Maio EIRELI", tipo_documento: "NFE", ultimo_nsu: 88210, max_nsu: 88240, atualizado_em: isoDaysFromNow(0) + "T07:55:00Z" },
  { id: 3, cliente: 4, cliente_nome: "Rotas Log Transportes S.A.", tipo_documento: "CTE", ultimo_nsu: 45110, max_nsu: 45110, atualizado_em: isoDaysFromNow(-1) + "T22:40:00Z" },
  { id: 4, cliente: 5, cliente_nome: "Tech Store Eletrônicos LTDA", tipo_documento: "NFE", ultimo_nsu: 12005, max_nsu: 12300, atualizado_em: isoDaysFromNow(-3) + "T10:05:00Z" },
];

const emitentes = [
  "Distribuidora Atacadão LTDA",
  "Frigorífico Boi Bravo S.A.",
  "Embalagens Premium ME",
  "Energia Sul Distribuidora",
  "Moinho Trigo de Ouro LTDA",
  "Logística Expressa do Brasil",
  "Fornecedora Hortifruti Vale Verde",
  "Indústria Química Solvex",
];

const tipos: TipoDocumento[] = ["NFE", "CTE", "NFSE", "NFCE"];
const statuses: StatusDocumento[] = ["CAPTURADO", "MANIFESTADO", "COMPLETO"];

function pad(n: number, len: number) {
  return String(n).padStart(len, "0");
}

function buildChave(seed: number): string {
  let s = "";
  let x = seed * 999331 + 17;
  for (let i = 0; i < 44; i++) {
    x = (x * 1103515245 + 12345) & 0x7fffffff;
    s += String(x % 10);
  }
  return s;
}

function competenciaFromOffset(monthsAgo: number): string {
  const d = new Date(today.getFullYear(), today.getMonth() - monthsAgo, 1);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1, 2)}`;
}

export const competencias: string[] = Array.from({ length: 6 }, (_, i) =>
  competenciaFromOffset(i),
);

function buildDocuments(): Documento[] {
  const docs: Documento[] = [];
  let id = 1000;
  const targetsPerClient = 70;
  for (const client of mockClientes) {
    for (let i = 0; i < targetsPerClient; i++) {
      const seed = client.id * 1000 + i;
      const monthsAgo = i % 6;
      const competencia = competenciaFromOffset(monthsAgo);
      const [yy, mm] = competencia.split("-").map(Number);
      const day = ((seed * 7) % 27) + 1;
      const data_emissao = `${yy}-${pad(mm, 2)}-${pad(day, 2)}`;
      const tipo = tipos[seed % tipos.length];
      const status = statuses[seed % statuses.length];
      const valor = Math.round((((seed * 37) % 9000) + 120 + (seed % 99)) * 100) / 100;
      docs.push({
        id: id++,
        chave: buildChave(seed),
        tipo_documento: tipo,
        cliente: client.id,
        cliente_nome: client.razao_social,
        emitente: emitentes[seed % emitentes.length],
        valor,
        data_emissao,
        competencia,
        status,
      });
    }
  }
  return docs.sort((a, b) => b.data_emissao.localeCompare(a.data_emissao));
}

export const mockDocumentos: Documento[] = buildDocuments();

export const mockLogs: LogCaptura[] = [
  { id: 1, cliente: 2, tipo_documento: "NFE",  sucesso: true,  mensagem: "12 documentos capturados", executado_em: isoDaysFromNow(0) + "T08:12:00Z" },
  { id: 2, cliente: 3, tipo_documento: "NFE",  sucesso: true,  mensagem: "3 documentos capturados",  executado_em: isoDaysFromNow(0) + "T07:55:00Z" },
  { id: 3, cliente: 4, tipo_documento: "CTE",  sucesso: false, mensagem: "Certificado A1 vencido",   executado_em: isoDaysFromNow(0) + "T07:40:00Z" },
  { id: 4, cliente: 5, tipo_documento: "NFE",  sucesso: false, mensagem: "Timeout na consulta SEFAZ", executado_em: isoDaysFromNow(-1) + "T23:10:00Z" },
  { id: 5, cliente: 2, tipo_documento: "NFCE", sucesso: true,  mensagem: "8 documentos capturados",  executado_em: isoDaysFromNow(-1) + "T08:12:00Z" },
  { id: 6, cliente: 3, tipo_documento: "NFSE", sucesso: true,  mensagem: "2 documentos capturados",  executado_em: isoDaysFromNow(-1) + "T08:00:00Z" },
];

export function buildMockXml(doc: Documento): string {
  return `<?xml version="1.0" encoding="UTF-8"?>
<nfeProc versao="4.00" xmlns="http://www.portalfiscal.inf.br/nfe">
  <NFe>
    <infNFe Id="${doc.tipo_documento}${doc.chave}">
      <ide>
        <cUF>35</cUF>
        <natOp>VENDA</natOp>
        <mod>${doc.tipo_documento}</mod>
        <dhEmi>${doc.data_emissao}T10:00:00-03:00</dhEmi>
        <competencia>${doc.competencia}</competencia>
      </ide>
      <emit>
        <xNome>${doc.emitente}</xNome>
      </emit>
      <dest>
        <xNome>${doc.cliente_nome}</xNome>
      </dest>
      <total>
        <ICMSTot>
          <vNF>${doc.valor.toFixed(2)}</vNF>
        </ICMSTot>
      </total>
      <status>${doc.status}</status>
    </infNFe>
  </NFe>
</nfeProc>`;
}