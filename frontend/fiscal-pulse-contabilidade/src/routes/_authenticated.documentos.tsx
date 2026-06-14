import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Copy,
  CalendarIcon,
  FileDown,
  Loader2,
  Package,
  X,
} from "lucide-react";
import { toast } from "sonner";

import { AppShell } from "@/components/app-shell";
import { useAuth } from "@/lib/auth";
import {
  downloadXml,
  exportarLote,
  listClientes,
  listDocumentos,
} from "@/lib/api";
import { competencias } from "@/lib/mock-data";
import type { Documento, DocumentoFilters } from "@/lib/types";
import {
  STATUS_LABEL,
  TIPO_LABEL,
  formatCompetencia,
  formatCurrency,
  formatDate,
  statusBadgeVariant,
} from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/_authenticated/documentos")({
  head: () => ({ meta: [{ title: "Documentos Capturados — Fiscal Tracker" }] }),
  component: DocumentosPage,
});

const PAGE_SIZE = 50;
const ALL = "__all__";

function DocumentosPage() {
  const { isStaff, user } = useAuth();

  const [cliente, setCliente] = useState<string>(ALL);
  const [competencia, setCompetencia] = useState<string>(ALL);
  const [tipo, setTipo] = useState<string>(ALL);
  const [status, setStatus] = useState<string>(ALL);
  const [inicio, setInicio] = useState<Date | undefined>();
  const [fim, setFim] = useState<Date | undefined>();
  const [page, setPage] = useState(1);
  const [exporting, setExporting] = useState(false);
  const [downloadingId, setDownloadingId] = useState<number | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  const clientesQuery = useQuery({
    queryKey: ["clientes"],
    queryFn: listClientes,
    enabled: isStaff,
  });

  const filters: DocumentoFilters = useMemo(
    () => ({
      cliente: cliente !== ALL ? cliente : undefined,
      competencia: competencia !== ALL ? competencia : undefined,
      tipo_documento: tipo !== ALL ? tipo : undefined,
      status: status !== ALL ? status : undefined,
      data_emissao_inicio: inicio ? format(inicio, "yyyy-MM-dd") : undefined,
      data_emissao_fim: fim ? format(fim, "yyyy-MM-dd") : undefined,
    }),
    [cliente, competencia, tipo, status, inicio, fim],
  );

  const docsQuery = useQuery({
    queryKey: ["documentos", filters, page, user?.id],
    queryFn: () => listDocumentos({ ...filters, page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });

  const data = docsQuery.data;
  const rows = data?.results ?? [];
  const total = data?.count ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  function resetPage<T>(setter: (v: T) => void) {
    return (v: T) => {
      setter(v);
      setPage(1);
    };
  }

  const hasFilters =
    cliente !== ALL ||
    competencia !== ALL ||
    tipo !== ALL ||
    status !== ALL ||
    !!inicio ||
    !!fim;

  function clearFilters() {
    setCliente(ALL);
    setCompetencia(ALL);
    setTipo(ALL);
    setStatus(ALL);
    setInicio(undefined);
    setFim(undefined);
    setPage(1);
  }

  async function copyChave(chave: string) {
    try {
      await navigator.clipboard.writeText(chave);
      setCopied(chave);
      toast.success("Chave de acesso copiada");
      setTimeout(() => setCopied(null), 1500);
    } catch {
      toast.error("Não foi possível copiar");
    }
  }

  async function handleDownload(doc: Documento) {
    setDownloadingId(doc.id);
    try {
      await downloadXml(doc);
      toast.success("XML baixado");
    } catch {
      toast.error("Falha ao baixar XML");
    } finally {
      setDownloadingId(null);
    }
  }

  async function handleExport() {
    setExporting(true);
    try {
      const count = await exportarLote(filters);
      toast.success(`Lote exportado: ${count} documento(s)`);
    } catch {
      toast.error("Falha ao exportar lote");
    } finally {
      setExporting(false);
    }
  }

  return (
    <AppShell title="Documentos Capturados">
      <div className="space-y-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-muted-foreground">
            {docsQuery.isLoading ? "Carregando..." : `${total} documento(s) encontrado(s)`}
          </p>
          <Button onClick={handleExport} disabled={exporting}>
            {exporting ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Package className="mr-2 h-4 w-4" />
            )}
            Exportar em Lote (ZIP)
          </Button>
        </div>

        {/* Filters */}
        <Card>
          <CardContent className="grid gap-3 p-4 md:grid-cols-3 xl:grid-cols-4">
            {isStaff && (
              <FilterField label="Cliente">
                <Select value={cliente} onValueChange={resetPage(setCliente)}>
                  <SelectTrigger>
                    <SelectValue placeholder="Todos os clientes" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL}>Todos os clientes</SelectItem>
                    {(clientesQuery.data ?? []).map((c) => (
                      <SelectItem key={c.id} value={String(c.id)}>
                        {c.razao_social}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </FilterField>
            )}

            <FilterField label="Competência">
              <Select value={competencia} onValueChange={resetPage(setCompetencia)}>
                <SelectTrigger>
                  <SelectValue placeholder="Todas" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>Todas</SelectItem>
                  {competencias.map((c) => (
                    <SelectItem key={c} value={c}>
                      {formatCompetencia(c)} ({c})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FilterField>

            <FilterField label="Tipo de documento">
              <Select value={tipo} onValueChange={resetPage(setTipo)}>
                <SelectTrigger>
                  <SelectValue placeholder="Todos" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>Todos os tipos</SelectItem>
                  <SelectItem value="NFE">NF-e</SelectItem>
                  <SelectItem value="CTE">CT-e</SelectItem>
                  <SelectItem value="NFSE">NFS-e</SelectItem>
                  <SelectItem value="NFCE">NFC-e</SelectItem>
                </SelectContent>
              </Select>
            </FilterField>

            <FilterField label="Status">
              <Select value={status} onValueChange={resetPage(setStatus)}>
                <SelectTrigger>
                  <SelectValue placeholder="Todos" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>Todos os status</SelectItem>
                  <SelectItem value="CAPTURADO">Capturado</SelectItem>
                  <SelectItem value="MANIFESTADO">Manifestado</SelectItem>
                  <SelectItem value="COMPLETO">Completo</SelectItem>
                </SelectContent>
              </Select>
            </FilterField>

            <FilterField label="Emissão (início)">
              <DateField value={inicio} onChange={resetPage(setInicio)} placeholder="Data início" />
            </FilterField>

            <FilterField label="Emissão (fim)">
              <DateField value={fim} onChange={resetPage(setFim)} placeholder="Data fim" />
            </FilterField>

            {hasFilters && (
              <div className="flex items-end">
                <Button variant="ghost" onClick={clearFilters} className="text-muted-foreground">
                  <X className="mr-2 h-4 w-4" />
                  Limpar filtros
                </Button>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Table */}
        <Card>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Chave de acesso</TableHead>
                  <TableHead>Tipo</TableHead>
                  {isStaff && <TableHead>Cliente</TableHead>}
                  <TableHead>Emitente</TableHead>
                  <TableHead className="text-right">Valor</TableHead>
                  <TableHead>Emissão</TableHead>
                  <TableHead>Competência</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Ações</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {docsQuery.isLoading ? (
                  Array.from({ length: 8 }).map((_, i) => (
                    <TableRow key={i}>
                      <TableCell colSpan={isStaff ? 9 : 8}>
                        <Skeleton className="h-6 w-full" />
                      </TableCell>
                    </TableRow>
                  ))
                ) : rows.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={isStaff ? 9 : 8}
                      className="py-12 text-center text-sm text-muted-foreground"
                    >
                      Nenhum documento encontrado com os filtros atuais.
                    </TableCell>
                  </TableRow>
                ) : (
                  rows.map((doc) => (
                    <TableRow key={doc.id}>
                      <TableCell>
                        <button
                          onClick={() => copyChave(doc.chave)}
                          className="group flex items-center gap-1.5 font-mono text-xs text-muted-foreground hover:text-foreground"
                          title="Clique para copiar a chave"
                        >
                          <span className="max-w-[180px] truncate">{doc.chave}</span>
                          {copied === doc.chave ? (
                            <Check className="h-3.5 w-3.5 text-success" />
                          ) : (
                            <Copy className="h-3.5 w-3.5 opacity-0 transition-opacity group-hover:opacity-100" />
                          )}
                        </button>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">{TIPO_LABEL[doc.tipo_documento]}</Badge>
                      </TableCell>
                      {isStaff && (
                        <TableCell className="max-w-[200px] truncate" title={doc.cliente_nome}>
                          {doc.cliente_nome}
                        </TableCell>
                      )}
                      <TableCell className="max-w-[200px] truncate" title={doc.emitente}>
                        {doc.emitente}
                      </TableCell>
                      <TableCell className="text-right font-medium tabular-nums">
                        {formatCurrency(doc.valor)}
                      </TableCell>
                      <TableCell className="whitespace-nowrap">{formatDate(doc.data_emissao)}</TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {formatCompetencia(doc.competencia)}
                      </TableCell>
                      <TableCell>
                        <Badge variant={statusBadgeVariant(doc.status)}>
                          {STATUS_LABEL[doc.status]}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleDownload(doc)}
                          disabled={downloadingId === doc.id}
                        >
                          {downloadingId === doc.id ? (
                            <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                          ) : (
                            <FileDown className="mr-1.5 h-4 w-4" />
                          )}
                          XML
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between border-t px-4 py-3 text-sm">
            <span className="text-muted-foreground">
              Página {page} de {totalPages}
            </span>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1 || docsQuery.isFetching}
              >
                <ChevronLeft className="h-4 w-4" />
                Anterior
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages || docsQuery.isFetching}
              >
                Próxima
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </Card>
      </div>
    </AppShell>
  );
}

function FilterField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="text-xs font-medium text-muted-foreground">{label}</label>
      {children}
    </div>
  );
}

function DateField({
  value,
  onChange,
  placeholder,
}: {
  value: Date | undefined;
  onChange: (d: Date | undefined) => void;
  placeholder: string;
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          className={cn(
            "w-full justify-start text-left font-normal",
            !value && "text-muted-foreground",
          )}
        >
          <CalendarIcon className="mr-2 h-4 w-4" />
          {value ? format(value, "dd/MM/yyyy") : <span>{placeholder}</span>}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
        <Calendar
          mode="single"
          selected={value}
          onSelect={onChange}
          initialFocus
          className={cn("p-3 pointer-events-auto")}
        />
      </PopoverContent>
    </Popover>
  );
}