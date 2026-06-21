import { createFileRoute } from "@tanstack/react-router";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  XCircle,
} from "lucide-react";

import { AppShell, StatCard } from "@/components/app-shell";
import { useAuth } from "@/lib/auth";
import { listCertificados, listDocumentos, listLogs } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  daysUntil,
  formatCompetencia,
  formatDateTime,
  TIPO_LABEL,
} from "@/lib/format";
import type { TipoDocumento } from "@/lib/types";

export const Route = createFileRoute("/_authenticated/dashboard")({
  head: () => ({ meta: [{ title: "Dashboard — CaptaFiscal" }] }),
  component: DashboardPage,
});

const CHART_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-5)",
];

function DashboardPage() {
  const { user } = useAuth();

  const docsQuery = useQuery({
    queryKey: ["documentos", "all", user?.id],
    queryFn: () => listDocumentos({ page: 1, page_size: 9999 }),
  });
  const certsQuery = useQuery({ queryKey: ["certificados", user?.id], queryFn: listCertificados });
  const logsQuery = useQuery({ queryKey: ["logs", user?.id], queryFn: listLogs });

  const docs = docsQuery.data?.results ?? [];
  const certs = certsQuery.data ?? [];
  const logs = logsQuery.data ?? [];

  const currentComp = useMemo(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  }, []);

  const totalMes = docs.filter((d) => d.competencia === currentComp).length;
  const canceladosMes = docs.filter(
    (d) => d.status === "CANCELADO" && d.competencia === currentComp
  ).length;
  const certAtivos = certs.filter((c) => c.ativo && daysUntil(c.validade) > 0).length;
  const certVencidos = certs.filter((c) => !c.ativo || daysUntil(c.validade) <= 0).length;
  const certAlerta = certs.filter((c) => {
    const d = daysUntil(c.validade);
    return d > 0 && d <= 30;
  }).length;
  const certProblematicos = certs
    .filter((c) => daysUntil(c.validade) <= 30)
    .sort((a, b) => daysUntil(a.validade) - daysUntil(b.validade));

  const byTipo = useMemo(() => {
    const map: Record<string, number> = {};
    docs.forEach((d) => {
      map[d.tipo_documento] = (map[d.tipo_documento] ?? 0) + 1;
    });
    return (Object.keys(TIPO_LABEL) as TipoDocumento[]).map((t) => ({
      name: TIPO_LABEL[t],
      value: map[t] ?? 0,
    }));
  }, [docs]);

  const byCompetencia = useMemo(() => {
    const map: Record<string, number> = {};
    docs.forEach((d) => {
      map[d.competencia] = (map[d.competencia] ?? 0) + 1;
    });
    return Object.entries(map)
      .sort((a, b) => a[0].localeCompare(b[0]))
      .slice(-6)
      .map(([comp, value]) => ({ name: formatCompetencia(comp), value }));
  }, [docs]);

  const loading = docsQuery.isLoading || certsQuery.isLoading;

  return (
    <AppShell title="Dashboard" subtitle={`Resumo de ${formatCompetencia(currentComp)}`}>
      <div className="space-y-6">
        {!loading && canceladosMes > 0 && (
          <Alert className="border-destructive/30 bg-destructive/5 [&>svg]:text-destructive">
            <Ban className="h-4 w-4" />
            <AlertTitle className="font-semibold">
              {canceladosMes} nota(s) cancelada(s) em {formatCompetencia(currentComp)}
            </AlertTitle>
            <AlertDescription className="text-sm text-muted-foreground">
              Documentos com status <strong>Cancelado</strong> foram detectados na competência atual.
              Verifique a aba <strong>Documentos</strong> filtrando por status "Cancelado" para confirmar o impacto no balancete.
            </AlertDescription>
          </Alert>
        )}
        {!loading && certProblematicos.length > 0 && (
          <Alert className="border-warning/30 bg-warning/5 [&>svg]:text-warning">
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle className="font-semibold">Certificados A1 com vencimento próximo</AlertTitle>
            <AlertDescription>
              <ul className="mt-1 space-y-1">
                {certProblematicos.map((c) => {
                  const d = daysUntil(c.validade);
                  return (
                    <li key={c.id} className="flex items-center gap-2 text-sm">
                      <span className="font-medium">{c.cliente_nome}</span>
                      <span className={d <= 0 ? "text-xs text-destructive" : "text-xs text-muted-foreground"}>
                        {d <= 0 ? "— Vencido" : d <= 7 ? `— ${d} dia(s) · Crítico` : `— ${d} dia(s)`}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </AlertDescription>
          </Alert>
        )}
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard
            label="Notas no mês"
            value={loading ? null : String(totalMes)}
            hint={formatCompetencia(currentComp)}
            loading={loading}
          />
          <StatCard
            label="Certificados ativos"
            value={loading ? null : String(certAtivos)}
            hint={`${certs.length} no total`}
            loading={loading}
            hintColor="#16A34A"
          />
          <StatCard
            label="Certificados vencidos"
            value={loading ? null : String(certVencidos)}
            hint={certAlerta > 0 ? `${certAlerta} vencendo em 30 dias` : "Nenhum alerta"}
            loading={loading}
            hintColor={certVencidos > 0 || certAlerta > 0 ? "#B45309" : "#94A3B8"}
          />
          <StatCard
            label="Canceladas no mês"
            value={loading ? null : String(canceladosMes)}
            hint={canceladosMes > 0 ? "Verificar na aba Documentos" : "Nenhuma cancelada"}
            loading={loading}
            hintColor={canceladosMes > 0 ? "#DC2626" : "#94A3B8"}
          />
        </div>

        <div className="grid gap-4 lg:grid-cols-5">
          <Card className="lg:col-span-3" style={{ border: "1px solid #F1F5F9" }}>
            <CardHeader>
              <CardTitle className="text-base" style={{ fontFamily: "'Plus Jakarta Sans', sans-serif", color: "#0F172A" }}>Volume por competência</CardTitle>
            </CardHeader>
            <CardContent>
              {loading ? (
                <Skeleton className="h-64 w-full" />
              ) : (
                <ResponsiveContainer width="100%" height={256}>
                  <BarChart data={byCompetencia}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                    <XAxis dataKey="name" tickLine={false} axisLine={false} fontSize={12} />
                    <YAxis tickLine={false} axisLine={false} fontSize={12} allowDecimals={false} />
                    <Tooltip
                      cursor={{ fill: "var(--muted)" }}
                      contentStyle={{
                        borderRadius: 8,
                        border: "1px solid var(--border)",
                        background: "var(--card)",
                        fontSize: 12,
                      }}
                    />
                    <Bar dataKey="value" fill="var(--chart-1)" radius={[6, 6, 0, 0]} name="Notas" />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          <Card className="lg:col-span-2" style={{ border: "1px solid #F1F5F9" }}>
            <CardHeader>
              <CardTitle className="text-base" style={{ fontFamily: "'Plus Jakarta Sans', sans-serif", color: "#0F172A" }}>Distribuição por tipo</CardTitle>
            </CardHeader>
            <CardContent>
              {loading ? (
                <Skeleton className="h-64 w-full" />
              ) : (
                <ResponsiveContainer width="100%" height={256}>
                  <PieChart>
                    <Pie
                      data={byTipo}
                      dataKey="value"
                      nameKey="name"
                      innerRadius={55}
                      outerRadius={90}
                      paddingAngle={2}
                    >
                      {byTipo.map((_, i) => (
                        <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{
                        borderRadius: 8,
                        border: "1px solid var(--border)",
                        background: "var(--card)",
                        fontSize: 12,
                      }}
                    />
                  </PieChart>
                </ResponsiveContainer>
              )}
              <div className="mt-2 grid grid-cols-2 gap-2">
                {byTipo.map((t, i) => (
                  <div key={t.name} className="flex items-center gap-2 text-xs">
                    <span
                      className="h-2.5 w-2.5 rounded-full"
                      style={{ background: CHART_COLORS[i % CHART_COLORS.length] }}
                    />
                    <span className="text-muted-foreground">{t.name}</span>
                    <span className="ml-auto font-medium">{t.value}</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>

        <Card style={{ border: "1px solid #F1F5F9" }}>
          <CardHeader>
            <CardTitle className="text-base" style={{ fontFamily: "'Plus Jakarta Sans', sans-serif", color: "#0F172A" }}>Atividade recente de captura</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {logsQuery.isLoading ? (
              <Skeleton className="h-32 w-full" />
            ) : logs.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                Nenhuma varredura registrada ainda.
              </p>
            ) : (
              logs.map((log) => (
                <div
                  key={log.id}
                  className="flex items-center gap-3 rounded-lg border bg-card px-3 py-2.5"
                >
                  {log.sucesso ? (
                    <CheckCircle2 className="h-5 w-5 shrink-0 text-success" />
                  ) : (
                    <XCircle className="h-5 w-5 shrink-0 text-destructive" />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">
                      {TIPO_LABEL[log.tipo_documento as TipoDocumento] ?? log.tipo_documento}
                      <span className="text-muted-foreground">
                        {" · "}{log.cliente_nome ?? `Cliente #${log.cliente}`}
                      </span>
                    </p>
                    <p className="truncate text-xs text-muted-foreground">{log.mensagem}</p>
                  </div>
                  <div className="hidden text-right sm:block">
                    <Badge variant={log.sucesso ? "success" : "destructive"}>
                      {log.sucesso ? "OK" : "ERRO"}
                    </Badge>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {formatDateTime(log.executado_em)}
                    </p>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}

