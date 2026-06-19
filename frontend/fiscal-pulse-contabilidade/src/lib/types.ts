export type TipoDocumento = "NFE" | "CTE" | "NFSE" | "NFCE";
export type StatusDocumento = "CAPTURADO" | "MANIFESTADO" | "COMPLETO" | "CANCELADO" | "SUBSTITUIDO";

export interface UserProfile {
  id: number;
  username: string;
  email: string;
  is_staff: boolean;
  is_active: boolean;
}

export interface Cliente {
  id: number;
  cnpj: string;
  razao_social: string;
  telefone?: string;
  ativo: boolean;
  criado_em?: string;
}

export interface Certificado {
  id: number;
  cliente: number;
  cliente_nome: string;
  nome_arquivo: string;
  validade: string; // ISO date
  ativo: boolean;
}

export interface ControleNSU {
  id: number;
  cliente: number;
  cliente_nome: string;
  tipo_documento: TipoDocumento;
  ultimo_nsu: number;
  max_nsu: number;
  atualizado_em: string;
}

export interface Documento {
  id: number;
  chave: string;
  tipo_documento: TipoDocumento;
  cliente: number;
  cliente_nome: string;
  emitente: string;
  valor: number;
  data_emissao: string; // YYYY-MM-DD
  competencia: string; // YYYY-MM
  /** true quando mês/ano de data_emissao difere de competencia */
  divergencia_competencia: boolean;
  status: StatusDocumento;
  /** "EMITENTE" (receita) | "TOMADOR" (despesa) | "" — preenchido apenas para NFS-e */
  papel_nfse: string;
}

export interface LogCaptura {
  id: number;
  cliente: number;
  cliente_nome?: string;
  tipo_documento: string;
  sucesso: boolean;
  mensagem: string;
  executado_em: string;
}

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface DocumentoFilters {
  cliente?: string;
  competencia?: string;
  tipo_documento?: string;
  status?: string;
  papel_nfse?: string;
  data_emissao_inicio?: string;
  data_emissao_fim?: string;
  competencia_divergente?: boolean;
  page?: number;
  page_size?: number;
}

export interface ReconciliacaoItem {
  cliente: number;
  cliente_nome: string;
  tipo_documento: string;
  ultimo_nsu: number;
  max_nsu: number;
  capturados: number;
  gap: number;
  atualizado_em: string;
}

export interface NovoClienteInput {
  cnpj: string;
  razao_social: string;
  telefone?: string;
}

export interface NovoCertificadoInput {
  cliente: number;
  arquivo: File;
  senha: string;
}
