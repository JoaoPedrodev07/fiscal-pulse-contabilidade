import { createFileRoute, Navigate } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Info,
  Loader2,
  Play,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";

import { AppShell } from "@/components/app-shell";
import { useAuth } from "@/lib/auth";
import { executarCaptura, listClientes, listLogs, listNSU } from "@/lib/api";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { formatCnpj, formatDateTime } from "@/lib/format";
import type { ControleNSU } from "@/lib/types";
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
              O Celery Beat executa a captura completa (NF-e, CT-e e NFS-e) para todos os clientes
              a cada 4 horas. Use o botão <strong className="text-foreground">Capturar agora</strong>{" "}
              para forçar uma captura manual imediata por cliente.
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

        <Card>
          <CardHeader className="pb-0">
            <CardTitle className="text-base">Status por cliente</CardTitle>
          </CardHeader>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Cliente</TableHead>
                  <TableHead>CNPJ</TableHead>
                  <TableHead className="text-center">NSU NF-e</TableHead>
                  <TableHead className="text-center">NSU CT-e</TableHead>
                  <TableHead className="text-center">NSU NFS-e</TableHead>
                  <TableHead>Última captura</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Ação</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {loading ? (
                  Array.from({ length: 4 }).map((_, i) => (
                    <TableRow key={i}>
                      <TableCell colSpan={8}>
                        <Skeleton className="h-6 w-full" />
                      </TableCell>
                    </TableRow>
                  ))
                ) : clientes.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={8}
                      className="py-12 text-center text-sm text-muted-foreground"
                    >
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
                        <TableCell className="text-center">
                          <NsuCell nsu={nsuCliente?.get("NFSE")} />
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
      </div>
    </AppShell>
  );
}

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
        toast.success("Captura concluída com sucesso");
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
