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
import { capturarNfseDireta, executarCaptura, getAuditoriaNSUResumo, listClientes, listLogs, listNSU, reconciliar } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { formatCnpj, formatDateTime } from "@/lib/format";
import type { AuditoriaNSUResumo, Cliente, ControleNSU, ReconciliacaoItem } from "@/lib/types";
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
  head: () => ({ meta: [{ title: "Captura / Sincronização — CaptaFiscal" }] }),
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
  const reconciliacaoQuery = useQuery({
    queryKey: ["reconciliacao"],
    queryFn: () => reconciliar(),
    enabled: isStaff,
  });
  const auditoriaQuery = useQuery({
    queryKey: ["auditoria-nsu"],
    queryFn: () => getAuditoriaNSUResumo(),
    enabled: isStaff,
  });

  if (!isStaff) return <Navigate to="/dashboard" replace />;

  const clientes = clientesQuery.data ?? [];
  const logs = logsQuery.data ?? [];
  const nsus = nsuQuery.data ?? [];

  const loading = clientesQuery.isLoading || logsQuery.isLoading || nsuQuery.isLoading;
  const reconcItems = reconciliacaoQuery.data ?? [];
  const temGap = reconcItems.some((r) => r.gap > 0);

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
    queryClient.invalidateQueries({ queryKey: ["reconciliacao"] });
  }

  return (
    <AppShell title="Captura / Sincronização" subtitle="Integre com SEFAZ ou dispare captura manual">
      <div className="space-y-5">
        <Alert className="border-primary/30 bg-primary/5">
          <Info className="h-4 w-4 text-primary" />
          <AlertTitle className="text-primary font-semibold">
            Captura automática ativa — intervalo de 1 hora
          </AlertTitle>
          <AlertDescription className="text-muted-foreground">
            <p>
              O robô executa <strong className="text-foreground">NF-e + CT-e + NFS-e</strong> (NSU
              incremental) para todos os clientes ativos a cada 1 hora. A busca por Chave de Acesso
              abaixo é um fallback cirúrgico para notas específicas.
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

        {/* Tabela NF-e / CT-e / NFS-e */}
        <Card>
          <CardHeader className="pb-0">
            <CardTitle className="text-base">NF-e / CT-e / NFS-e — Status por cliente</CardTitle>
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
                    <TableCell colSpan={8} className="py-12 text-center text-sm text-muted-foreground">
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

        {/* Painel NFS-e — fallback cirúrgico */}
        <NfsePanel clientes={clientes} onSettled={invalidarDados} />

        {/* Auditoria NSU */}
        <AuditoriaCard
          isLoading={auditoriaQuery.isLoading}
          resumo={auditoriaQuery.data}
        />

        {/* Painel de Reconciliação NSU */}
        <Card>
          <CardHeader className="pb-0">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">Reconciliação — capturados vs. disponível na SEFAZ</CardTitle>
              {temGap && (
                <Badge variant="warning" className="gap-1">
                  <AlertTriangle className="h-3 w-3" />
                  Gap detectado
                </Badge>
              )}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              Compare o que está no banco com o maxNSU reportado pela SEFAZ antes de fechar a competência.
            </p>
          </CardHeader>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Cliente</TableHead>
                  <TableHead>Tipo</TableHead>
                  <TableHead className="text-center">Capturados</TableHead>
                  <TableHead className="text-center">Último NSU</TableHead>
                  <TableHead className="text-center">Max NSU</TableHead>
                  <TableHead className="text-center">Gap</TableHead>
                  <TableHead>Situação</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {reconciliacaoQuery.isLoading ? (
                  Array.from({ length: 3 }).map((_, i) => (
                    <TableRow key={i}>
                      <TableCell colSpan={7}>
                        <Skeleton className="h-6 w-full" />
                      </TableCell>
                    </TableRow>
                  ))
                ) : reconcItems.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={7} className="py-10 text-center text-sm text-muted-foreground">
                      Nenhum controle de NSU registrado ainda.
                    </TableCell>
                  </TableRow>
                ) : (
                  reconcItems.map((r) => (
                    <ReconciliacaoRow key={`${r.cliente}-${r.tipo_documento}`} item={r} />
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </Card>
      </div>
    </AppShell>
  );
}

// ── Reconciliação ────────────────────────────────────────────────────────────

function ReconciliacaoRow({ item }: { item: ReconciliacaoItem }) {
  const temGap = item.gap > 0;
  return (
    <TableRow className={temGap ? "bg-warning/5" : undefined}>
      <TableCell className="font-medium">{item.cliente_nome}</TableCell>
      <TableCell>
        <Badge variant="outline">{item.tipo_documento}</Badge>
      </TableCell>
      <TableCell className="text-center tabular-nums">{item.capturados.toLocaleString("pt-BR")}</TableCell>
      <TableCell className="text-center tabular-nums">{item.ultimo_nsu.toLocaleString("pt-BR")}</TableCell>
      <TableCell className="text-center tabular-nums">{item.max_nsu.toLocaleString("pt-BR")}</TableCell>
      <TableCell className="text-center">
        {temGap ? (
          <span className="inline-flex items-center gap-1 text-sm font-semibold text-warning">
            <AlertTriangle className="h-3.5 w-3.5" />
            {item.gap.toLocaleString("pt-BR")}
          </span>
        ) : (
          <span className="text-sm text-muted-foreground">0</span>
        )}
      </TableCell>
      <TableCell>
        {temGap ? (
          <Badge variant="warning">Incompleto</Badge>
        ) : (
          <div className="flex items-center gap-1.5">
            <CheckCircle2 className="h-4 w-4 text-success" />
            <Badge variant="success">Consistente</Badge>
          </div>
        )}
      </TableCell>
    </TableRow>
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
        <CardTitle className="text-base">NFS-e — Busca cirúrgica por Chave de Acesso</CardTitle>
        <p className="text-xs text-muted-foreground">
          <strong className="text-foreground">A captura automática já cobre NFS-e a cada 1h.</strong>{" "}
          Use este formulário apenas se uma nota específica não aparecer após o ciclo automático.
          Não é necessário informar senha — o certificado do cliente é usado automaticamente do cofre.
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

// ── Auditoria NSU ────────────────────────────────────────────────────────────

const RESULTADO_LABEL: Record<string, string> = {
  SALVO:             'Documentos salvos',
  DUPLICADO:         'Já existiam no banco',
  CHAVE_INVALIDA:    'Chave inválida',
  XML_VAZIO:         'XML vazio',
  XML_INVALIDO:      'XML indecodificável',
  ERRO_PERSISTENCIA: 'Erro ao persistir',
};

const RESULTADO_VARIANT: Record<string, 'success' | 'outline' | 'warning' | 'destructive'> = {
  SALVO:             'success',
  DUPLICADO:         'outline',
  CHAVE_INVALIDA:    'warning',
  XML_VAZIO:         'warning',
  XML_INVALIDO:      'destructive',
  ERRO_PERSISTENCIA: 'destructive',
};

function AuditoriaCard({
  isLoading,
  resumo,
}: {
  isLoading: boolean;
  resumo?: AuditoriaNSUResumo;
}) {
  const salvos     = resumo?.por_resultado?.SALVO ?? 0;
  const descartados = resumo
    ? resumo.total - salvos - (resumo.por_resultado?.DUPLICADO ?? 0)
    : 0;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Auditoria NSU — destino de cada nota recebida</CardTitle>
          {!isLoading && resumo && resumo.total === 0 && (
            <Badge variant="outline" className="text-xs">Sem registros ainda</Badge>
          )}
        </div>
        <p className="text-xs text-muted-foreground mt-1">
          Mostra o que aconteceu com cada NSU retornado pelo ADN da SEFAZ,
          incluindo os que não geraram documento.
        </p>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-5 w-full" />
            <Skeleton className="h-5 w-3/4" />
          </div>
        ) : !resumo || resumo.total === 0 ? (
          <p className="text-sm text-muted-foreground">
            Nenhum NSU auditado ainda. Os registros aparecem após a próxima captura automática.
          </p>
        ) : (
          <div className="space-y-3">
            {/* Resumo numérico rápido */}
            <div className="flex flex-wrap gap-4 text-sm">
              <span>
                <span className="font-semibold tabular-nums">{resumo.total.toLocaleString('pt-BR')}</span>
                {' '}NSUs processados
              </span>
              <span className="text-success font-medium">
                <span className="tabular-nums">{salvos.toLocaleString('pt-BR')}</span> salvos
              </span>
              {descartados > 0 && (
                <span className="text-warning font-medium">
                  <span className="tabular-nums">{descartados.toLocaleString('pt-BR')}</span> descartados
                </span>
              )}
            </div>

            {/* Breakdown por resultado */}
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Resultado</TableHead>
                  <TableHead className="text-right">Quantidade</TableHead>
                  <TableHead className="text-right w-24">%</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {Object.entries(resumo.por_resultado)
                  .sort(([, a], [, b]) => b - a)
                  .map(([resultado, total]) => (
                    <TableRow key={resultado}>
                      <TableCell>
                        <Badge variant={RESULTADO_VARIANT[resultado] ?? 'outline'}>
                          {RESULTADO_LABEL[resultado] ?? resultado}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right tabular-nums font-medium">
                        {total.toLocaleString('pt-BR')}
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">
                        {resumo.total > 0
                          ? `${((total / resumo.total) * 100).toFixed(1)}%`
                          : '—'}
                      </TableCell>
                    </TableRow>
                  ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
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
