import type { StatusDocumento, TipoDocumento } from "./types";

export function formatCurrency(value: number): string {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(value);
}

export function formatDate(iso: string): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
}

export function formatDateTime(iso: string): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return date.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

export function formatCnpj(cnpj: string | null): string {
  if (!cnpj) return "—";
  const digits = cnpj.replace(/\D/g, "");
  if (digits.length !== 14) return cnpj;
  return digits.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, "$1.$2.$3/$4-$5");
}

export function formatCompetencia(comp: string): string {
  if (!comp) return "—";
  const [y, m] = comp.split("-");
  const meses = [
    "Jan",
    "Fev",
    "Mar",
    "Abr",
    "Mai",
    "Jun",
    "Jul",
    "Ago",
    "Set",
    "Out",
    "Nov",
    "Dez",
  ];
  return `${meses[Number(m) - 1]}/${y}`;
}

export const TIPO_LABEL: Record<TipoDocumento, string> = {
  NFE: "NF-e",
  CTE: "CT-e",
  NFSE: "NFS-e",
  NFCE: "NFC-e",
};

export const STATUS_LABEL: Record<StatusDocumento, string> = {
  CAPTURADO:   "Capturado",
  MANIFESTADO: "Manifestado",
  COMPLETO:    "Autorizada",
  CANCELADO:   "Cancelada",
  SUBSTITUIDO: "Substituída",
};

export function statusBadgeVariant(
  status: StatusDocumento,
): "warning" | "info" | "success" | "destructive" | "secondary" {
  switch (status) {
    case "CAPTURADO":
      return "warning";
    case "MANIFESTADO":
      return "info";
    case "COMPLETO":
      return "success";
    case "CANCELADO":
      return "destructive";
    case "SUBSTITUIDO":
      return "secondary";
  }
}

export function daysUntil(iso: string): number {
  const target = new Date(iso.slice(0, 10) + "T00:00:00");
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  return Math.round((target.getTime() - now.getTime()) / 86_400_000);
}