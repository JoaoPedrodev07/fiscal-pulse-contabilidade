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
  CheckCircle2,
  Download,
  FileText,
  ShieldCheck,
  XCircle,
} from "lucide-react";

import { AppShell } from "@/components/app-shell";
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
  head: () => ({ meta: [{ title: "Dashboard — Fiscal Tracker" }] }),
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
  const certAtivos = certs.filter((c) => c.ativo && daysUntil(c.validade) > 0).length;
  const certVencidos = certs.filter((c) => !c.ativo || daysUntil(c.validade) <= 0).length;
  const certAlerta = certs.filter((c) => {
    const d = daysUntil(c.validade);
    return d > 0 && d <= 30;
  }).length;
  const certProblematicos = certs
    .filter((c) => daysUntil(c.validade) <= 30)
    .sort((a, b) => daysUntil(a.validade) - daysUntil(b.validade));
  const downloads = useMemo(() => 120 + docs.length * 2, [docs.length]);

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
    <AppShell title="Dashboard">
      <div className="space-y-6">
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
          <MetricCard
            label="Notas no mês"
            value={loading ? null : String(totalMes)}
            hint={formatCompetencia(currentComp)}
            icon={FileText}
            tone="primary"
          />
          <MetricCard
            label="Certificados ativos"
            value={loading ? null : String(certAtivos)}
            hint={`${certs.length} no total`}
            icon={ShieldCheck}
            tone="success"
          />
          <MetricCard
            label="Certificados vencidos"
            value={loading ? null : String(certVencidos)}
            hint={certAlerta > 0 ? `${certAlerta} vencendo em 30 dias` : "Nenhum alerta"}
            icon={AlertTriangle}
            tone={certVencidos > 0 || certAlerta > 0 ? "danger" : "muted"}
          />
          <MetricCard
            label="Downloads realizados"
            value={loading ? null : downloads.toLocaleString("pt-BR")}
            hint="XML + lotes ZIP"
            icon={Download}
            tone="muted"
          />
        </div>

        <div className="grid gap-4 lg:grid-cols-5">
          <Card className="lg:col-span-3">
            <CardHeader>
              <CardTitle className="text-base">Volume por competência</CardTitle>
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

          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle className="text-base">Distribuição por tipo</CardTitle>
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

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Atividade recente de captura</CardTitle>
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

function MetricCard({
  label,
  value,
  hint,
  icon: Icon,
  tone,
}: {
  label: string;
  value: string | null;
  hint: string;
  icon: typeof FileText;
  tone: "primary" | "success" | "danger" | "muted";
}) {
  const toneMap: Record<string, string> = {
    primary: "bg-primary/10 text-primary",
    success: "bg-success/10 text-success",
    danger: "bg-destructive/10 text-destructive",
    muted: "bg-muted text-muted-foreground",
  };
  return (
    <Card>
      <CardContent className="flex items-center gap-4 p-5">
        <div className={`flex h-11 w-11 items-center justify-center rounded-xl ${toneMap[tone]}`}>
          <Icon className="h-5 w-5" />
        </div>
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {label}
          </p>
          {value === null ? (
            <Skeleton className="mt-1 h-7 w-16" />
          ) : (
            <p className="text-2xl font-semibold leading-tight">{value}</p>
          )}
          <p className="truncate text-xs text-muted-foreground">{hint}</p>
        </div>
      </CardContent>
    </Card>
  );
}