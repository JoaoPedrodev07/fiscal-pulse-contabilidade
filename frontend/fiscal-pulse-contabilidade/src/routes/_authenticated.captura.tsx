import { createFileRoute, Navigate } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Info,
  Loader2,
  Play,
  Search,
  XCircle,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { AppShell } from "@/components/app-shell";
import { useAuth } from "@/lib/auth";
import { capturarNfseDireta, executarCaptura, listClientes, listLogs, listNSU } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { formatCnpj, formatDateTime } from "@/lib/format";
import type { Cliente, ControleNSU } from "@/lib/types";
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

export const Route = createFileRoute("/_authenticated/captura")({
  head: () => ({ meta: [{ title: "Captura / Sincronização — Fiscal Tracker" }] }),
  component: CapturaPage,
});

function CapturaPage() {
  const { isStaff } = useAuth();
  const queryClient = useQueryClient();

  const clientesQuery = useQuery({
    queryKey: ["clientes"],
    queryFn: listClientes,
    enabled: isStaff,
  });
  const logsQuery = useQuery({
    queryKey: ["logs"],
    queryFn: listLogs,
    enabled: isStaff,
  });
  const nsuQuery = useQuery({
    queryKey: ["nsu"],
    queryFn: listNSU,
    enabled: isStaff,
  });

  if (!isStaff) return <Navigate to="/dashboard" replace />;

  const clientes = clientesQuery.data ?? [];
  const logs = logsQuery.data ?? [];
  const nsus = nsuQuery.data ?? [];

  const loading = clientesQuery.isLoading || logsQuery.isLoading || nsuQuery.isLoading;

  const nsuMap = new Map<number, Map<string, ControleNSU>>();
  nsus.forEach((n) => {
    if (!nsuMap.has(n.cliente)) nsuMap.set(n.cliente, new Map());
    nsuMap.get(n.cliente)!.set(n.tipo_documento, n);
  });

  const lastLogMap = new Map<
    number,
    { sucesso: boolean; mensagem: string; executado_em: string }
  >();
  [...logs]
    .sort((a, b) => b.executado_em.localeCompare(a.executado_em))
    .forEach((l) => {
      if (!lastLogMap.has(l.cliente)) {
        lastLogMap.set(l.cliente, {
          sucesso: l.sucesso,
          mensagem: l.mensagem,
          executado_em: l.executado_em,
        });
      }
    });

  function invalidarDados() {
    queryClient.invalidateQueries({ queryKey: ["nsu"] });
    queryClient.invalidateQueries({ queryKey: ["logs"] });
    queryClient.invalidateQueries({ queryKey: ["documentos"] });
  }

  return (
    <AppShell title="Captura / Sincronização">
      <div className="space-y-5">
        <Alert className="border-primary/30 bg-primary/5">
          <Info className="h-4 w-4 text-primary" />
          <AlertTitle className="text-primary font-semibold">
            Captura automática ativa — intervalo de 4 horas
          </AlertTitle>
          <AlertDescription className="text-muted-foreground">
            <p>
              O Celery Beat executa NF-e + CT-e (NSU incremental) para todos os clientes a cada 4
              horas. NFS-e é capturada sob demanda pela Chave de Acesso (ADN Nacional, NT 008/2026).
            </p>
            <ul className="mt-2 space-y-1.5 text-xs">
              <li className="flex items-start gap-1.5">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
                <span>
                  <span className="font-medium text-foreground">Janela de 90 dias (NF-e / CT-e):</span>{" "}
                  documentos ficam disponíveis na DistribuiçãoDFe por aproximadamente 90 dias.
                </span>
              </li>
              <li className="flex items-start gap-1.5">
                <Clock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                <span>
                  <span className="font-medium text-foreground">Ambiente de homologação:</span>{" "}
                  capturas apontam para os web services de homologação da SEFAZ.
                </span>
              </li>
            </ul>
          </AlertDescription>
        </Alert>

        {/* Tabela NF-e / CT-e */}
        <Card>
          <CardHeader className="pb-0">
            <CardTitle className="text-base">NF-e / CT-e — Status por cliente</CardTitle>
          </CardHeader>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Cliente</TableHead>
                  <TableHead>CNPJ</TableHead>
                  <TableHead className="text-center">NSU NF-e</TableHead>
                  <TableHead className="text-center">NSU CT-e</TableHead>
                  <TableHead>Última captura</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Ação</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {loading ? (
                  Array.from({ length: 4 }).map((_, i) => (
                    <TableRow key={i}>
                      <TableCell colSpan={7}>
                        <Skeleton className="h-6 w-full" />
                      </TableCell>
                    </TableRow>
                  ))
                ) : clientes.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={7} className="py-12 text-center text-sm text-muted-foreground">
                      Nenhum cliente cadastrado.
                    </TableCell>
                  </TableRow>
                ) : (
                  clientes.map((c) => {
                    const nsuCliente = nsuMap.get(c.id);
                    const lastLog = lastLogMap.get(c.id);
                    return (
                      <TableRow key={c.id}>
                        <TableCell className="font-medium">{c.razao_social}</TableCell>
                        <TableCell className="font-mono text-xs tabular-nums text-muted-foreground">
                          {formatCnpj(c.cnpj)}
                        </TableCell>
                        <TableCell className="text-center">
                          <NsuCell nsu={nsuCliente?.get("NFE")} />
                        </TableCell>
                        <TableCell className="text-center">
                          <NsuCell nsu={nsuCliente?.get("CTE")} />
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                          {lastLog ? formatDateTime(lastLog.executado_em) : "—"}
                        </TableCell>
                        <TableCell>
                          {!lastLog ? (
                            <span className="text-xs text-muted-foreground">Sem registros</span>
                          ) : lastLog.sucesso ? (
                            <div className="flex items-center gap-1.5">
                              <CheckCircle2 className="h-4 w-4 text-success" />
                              <Badge variant="success">OK</Badge>
                            </div>
                          ) : (
                            <div className="flex items-center gap-1.5">
                              <XCircle className="h-4 w-4 text-destructive" />
                              <Badge variant="destructive">ERRO</Badge>
                            </div>
                          )}
                        </TableCell>
                        <TableCell className="text-right">
                          <CapturaButton clienteId={c.id} onSettled={invalidarDados} />
                        </TableCell>
                      </TableRow>
                    );
                  })
                )}
              </TableBody>
            </Table>
          </div>
        </Card>

        {/* Painel NFS-e sob demanda */}
        <NfsePanel clientes={clientes} onSettled={invalidarDados} />
      </div>
    </AppShell>
  );
}

// ── Painel NFS-e ─────────────────────────────────────────────────────────────

function NfsePanel({
  clientes,
  onSettled,
}: {
  clientes: Cliente[];
  onSettled: () => void;
}) {
  const [clienteId, setClienteId] = useState<string>("");
  const [chave, setChave] = useState("");

  const mutation = useMutation({
    mutationFn: () => capturarNfseDireta(Number(clienteId), chave),
    onSuccess: (resultado) => {
      if (resultado.sucesso) {
        toast.success("NFS-e capturada com sucesso");
        setChave("");
      } else {
        toast.error(resultado.mensagem);
      }
      onSettled();
    },
    onError: (err: Error) => {
      toast.error(err.message || "Falha na captura da NFS-e");
      onSettled();
    },
  });

  const chaveValida = chave.replace(/\D/g, "").length === 44;
  const podeCapturar = !!clienteId && chaveValida && !mutation.isPending;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!podeCapturar) return;
    mutation.mutate();
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">NFS-e — Captura por Chave de Acesso</CardTitle>
        <p className="text-xs text-muted-foreground">
          API ADN Nacional (NT 008/2026). Requer liberação de IP dedicado junto ao Serpro.
        </p>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4 sm:flex-row sm:items-end">
          <div className="flex-1 space-y-1.5">
            <Label htmlFor="nfse-cliente">Cliente</Label>
            <Select value={clienteId} onValueChange={setClienteId}>
              <SelectTrigger id="nfse-cliente">
                <SelectValue placeholder="Selecionar cliente…" />
              </SelectTrigger>
              <SelectContent>
                {clientes.map((c) => (
                  <SelectItem key={c.id} value={String(c.id)}>
                    {c.razao_social}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex-[2] space-y-1.5">
            <Label htmlFor="nfse-chave">Chave de Acesso (44 dígitos)</Label>
            <Input
              id="nfse-chave"
              value={chave}
              onChange={(e) => setChave(e.target.value.replace(/\D/g, "").slice(0, 44))}
              placeholder="00000000000000000000000000000000000000000000"
              className="font-mono text-sm"
              maxLength={44}
            />
            {chave.length > 0 && chave.length < 44 && (
              <p className="text-xs text-destructive">{44 - chave.length} dígito(s) restante(s)</p>
            )}
          </div>

          <Button type="submit" disabled={!podeCapturar} className="shrink-0">
            {mutation.isPending ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <Search className="mr-1.5 h-4 w-4" />
            )}
            {mutation.isPending ? "Buscando…" : "Capturar NFS-e"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

// ── Subcomponentes ────────────────────────────────────────────────────────────

function CapturaButton({
  clienteId,
  onSettled,
}: {
  clienteId: number;
  onSettled: () => void;
}) {
  const mutation = useMutation({
    mutationFn: () => executarCaptura(clienteId),
    onSuccess: (resultado) => {
      if (resultado.sucesso) {
        toast.success("Captura NF-e + CT-e concluída com sucesso");
      } else {
        toast.error(`Captura falhou: ${resultado.mensagem}`);
      }
      onSettled();
    },
    onError: (err: Error) => {
      toast.error(err.message || "Falha na captura");
      onSettled();
    },
  });

  return (
    <Button
      variant="ghost"
      size="sm"
      disabled={mutation.isPending}
      onClick={() => mutation.mutate()}
    >
      {mutation.isPending ? (
        <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
      ) : (
        <Play className="mr-1.5 h-4 w-4" />
      )}
      {mutation.isPending ? "Capturando…" : "Capturar agora"}
    </Button>
  );
}

function NsuCell({ nsu }: { nsu?: ControleNSU }) {
  if (!nsu) return <span className="text-xs text-muted-foreground">—</span>;
  return (
    <div className="text-xs tabular-nums">
      <span className="font-medium">{nsu.ultimo_nsu.toLocaleString("pt-BR")}</span>
      {nsu.max_nsu > 0 && (
        <span className="text-muted-foreground">
          {" "}/ {nsu.max_nsu.toLocaleString("pt-BR")}
        </span>
      )}
    </div>
  );
}
