import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  BadgeCheck,
  ChevronLeft,
  ChevronRight,
  Download,
  FileSpreadsheet,
  Loader2,
  Search,
} from "lucide-react";
import { toast } from "sonner";

import { AppShell } from "@/components/app-shell";
import { useAuth } from "@/lib/auth";
import { exportarRelatorioNfse, listClientes, listNotasTratadas } from "@/lib/api";
import type { NotaTratada, NotaTratadaFilters, ParecerNfse } from "@/lib/types";

export const Route = createFileRoute("/_authenticated/relatorios")({
  component: RelatoriosPage,
});

const PARECER_STYLE: Record<ParecerNfse, { bg: string; text: string; dot: string }> = {
  "Válida":                        { bg: "#D1FAE5", text: "#065F46", dot: "#10B981" },
  "Válida (DIVERGÊNCIA RETENÇÃO)": { bg: "#FEF3C7", text: "#92400E", dot: "#F59E0B" },
  "Cancelada":                     { bg: "#FEE2E2", text: "#991B1B", dot: "#EF4444" },
  "Substituída":                   { bg: "#E0E7FF", text: "#3730A3", dot: "#6366F1" },
};

function ParecerBadge({ parecer }: { parecer: ParecerNfse }) {
  const s = PARECER_STYLE[parecer] ?? { bg: "#F1F5F9", text: "#475569", dot: "#94A3B8" };
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium"
      style={{ background: s.bg, color: s.text }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: s.dot }} />
      {parecer}
    </span>
  );
}

function fmt(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(v);
}

function RelatoriosPage() {
  const { isStaff } = useAuth();

  const [filters, setFilters] = useState<NotaTratadaFilters>({});
  const [page, setPage] = useState(1);
  const [busca, setBusca] = useState("");

  const clientesQuery = useQuery({
    queryKey: ["clientes"],
    queryFn: listClientes,
    staleTime: 60_000,
  });

  const notasQuery = useQuery({
    queryKey: ["notas-tratadas", filters, page],
    queryFn: () => listNotasTratadas({ ...filters, search: busca || undefined, page }),
    placeholderData: keepPreviousData,
    enabled: isStaff,
  });

  const exportMutation = useMutation({
    mutationFn: () => exportarRelatorioNfse({ ...filters, search: busca || undefined }),
    onSuccess: () => toast.success("Planilha baixada com sucesso."),
    onError: (e: Error) => toast.error(e.message),
  });

  function applyFilter(key: keyof NotaTratadaFilters, value: string) {
    setFilters((prev) => ({ ...prev, [key]: value || undefined }));
    setPage(1);
  }

  const notas = notasQuery.data?.results ?? [];
  const total = notasQuery.data?.count ?? 0;
  const totalPages = Math.ceil(total / 50);

  if (!isStaff) {
    return (
      <AppShell>
        <div className="flex items-center gap-2 p-8 text-sm text-gray-500">
          <AlertTriangle className="h-4 w-4" />
          Acesso restrito a funcionários do escritório.
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <div className="space-y-6 p-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">Relatórios NFS-e</h1>
            <p className="mt-0.5 text-sm text-gray-500">
              Dados tratados e parecer fiscal das notas capturadas
            </p>
          </div>
          <button
            onClick={() => exportMutation.mutate()}
            disabled={exportMutation.isPending || notasQuery.isLoading}
            className="inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            style={{ background: "#2563EB" }}
          >
            {exportMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <FileSpreadsheet className="h-4 w-4" />
            )}
            Exportar Excel
          </button>
        </div>

        {/* Filtros */}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <select
            className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={filters.cliente ?? ""}
            onChange={(e) => applyFilter("cliente", e.target.value)}
          >
            <option value="">Todos os clientes</option>
            {(clientesQuery.data ?? []).map((c) => (
              <option key={c.id} value={String(c.id)}>
                {c.razao_social}
              </option>
            ))}
          </select>

          <input
            type="text"
            placeholder="Competência (MM/AAAA)"
            className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={filters.data_competencia ?? ""}
            onChange={(e) => applyFilter("data_competencia", e.target.value)}
          />

          <select
            className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={filters.parecer ?? ""}
            onChange={(e) => applyFilter("parecer", e.target.value)}
          >
            <option value="">Todos os pareceres</option>
            <option value="Válida">Válida</option>
            <option value="Válida (DIVERGÊNCIA RETENÇÃO)">Divergência Retenção</option>
            <option value="Cancelada">Cancelada</option>
            <option value="Substituída">Substituída</option>
          </select>

          <select
            className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={filters.papel_nfse ?? ""}
            onChange={(e) => applyFilter("papel_nfse", e.target.value)}
          >
            <option value="">Emitente + Tomador</option>
            <option value="EMITENTE">Receitas (Emitente)</option>
            <option value="TOMADOR">Despesas (Tomador)</option>
          </select>
        </div>

        {/* Busca */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Buscar por emitente, tomador ou nº NFS-e..."
            className="w-full rounded-lg border border-gray-200 bg-white py-2 pl-9 pr-4 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={busca}
            onChange={(e) => {
              setBusca(e.target.value);
              setPage(1);
            }}
          />
        </div>

        {/* Tabela */}
        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
          {notasQuery.isLoading ? (
            <div className="flex items-center justify-center gap-2 p-12 text-gray-400">
              <Loader2 className="h-5 w-5 animate-spin" />
              Carregando...
            </div>
          ) : notas.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 p-12 text-gray-400">
              <BadgeCheck className="h-8 w-8" />
              <p className="text-sm">Nenhuma nota encontrada para os filtros selecionados.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100 bg-gray-50">
                    {[
                      "Nº NFS-e", "Competência", "Emitente", "Tomador",
                      "Valor Serviço", "Ret. PIS", "Ret. COFINS", "Ret. CSLL",
                      "Ret. IRRF", "Ret. INSS", "Parecer",
                    ].map((h) => (
                      <th
                        key={h}
                        className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {notas.map((nota) => (
                    <NotaRow key={nota.id} nota={nota} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Paginação */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between text-sm text-gray-600">
            <span>
              {total} nota{total !== 1 ? "s" : ""} encontrada{total !== 1 ? "s" : ""}
            </span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                className="rounded-lg border border-gray-200 p-1.5 disabled:opacity-40"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <span>
                {page} / {totalPages}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="rounded-lg border border-gray-200 p-1.5 disabled:opacity-40"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}

function NotaRow({ nota }: { nota: NotaTratada }) {
  return (
    <tr className="hover:bg-gray-50">
      <td className="px-4 py-3 font-mono text-xs text-gray-700">{nota.numero_nfse || "—"}</td>
      <td className="px-4 py-3 text-gray-700">{nota.data_competencia || "—"}</td>
      <td className="px-4 py-3">
        <div className="max-w-[160px]">
          <p className="truncate font-medium text-gray-900">{nota.emitente_nome || "—"}</p>
          <p className="truncate text-xs text-gray-400">{nota.emitente_cnpj}</p>
        </div>
      </td>
      <td className="px-4 py-3">
        <div className="max-w-[160px]">
          <p className="truncate text-gray-700">{nota.tomador_nome || "—"}</p>
          <p className="truncate text-xs text-gray-400">{nota.tomador_doc}</p>
        </div>
      </td>
      <td className="px-4 py-3 text-right text-gray-700">{fmt(nota.valor_servico)}</td>
      <td className="px-4 py-3 text-right text-gray-700">{fmt(nota.ret_pis)}</td>
      <td className="px-4 py-3 text-right text-gray-700">{fmt(nota.ret_cofins)}</td>
      <td className="px-4 py-3 text-right text-gray-700">{fmt(nota.ret_csll)}</td>
      <td className="px-4 py-3 text-right text-gray-700">{fmt(nota.ret_irrf)}</td>
      <td className="px-4 py-3 text-right text-gray-700">{fmt(nota.ret_inss)}</td>
      <td className="px-4 py-3">
        <ParecerBadge parecer={nota.parecer} />
      </td>
    </tr>
  );
}
