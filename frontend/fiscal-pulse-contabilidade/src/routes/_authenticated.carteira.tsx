import { createFileRoute, Navigate } from "@tanstack/react-router";
import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Eye,
  EyeOff,
  FileKey,
  Loader2,
  Lock,
  Pencil,
  Plus,
  ShieldAlert,
  ShieldCheck,
  Trash2,
  Upload,
  UserPlus,
} from "lucide-react";

import { toast } from "sonner";
import { z } from "zod";

import { AppShell } from "@/components/app-shell";
import { useAuth } from "@/lib/auth";
import { createCertificado, createCliente, deleteCliente, listCertificados, listClientes, patchCliente } from "@/lib/api";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import type { Certificado, NovoClienteInput, RegimeTributario } from "@/lib/types";
import { REGIME_LABELS } from "@/lib/types";
import { daysUntil, formatCnpj, formatDate } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/_authenticated/carteira")({
  head: () => ({ meta: [{ title: "Carteira de Clientes — CaptaFiscal" }] }),
  component: CarteiraPage,
});

const REGIME_STYLE: Record<RegimeTributario, { bg: string; text: string }> = {
  "":    { bg: "#F1F5F9", text: "#64748B" },
  MEI:   { bg: "#EFF6FF", text: "#1D4ED8" },
  SN:    { bg: "#F0FDF4", text: "#15803D" },
  LP:    { bg: "#FFF7ED", text: "#C2410C" },
  LR:    { bg: "#FDF4FF", text: "#7E22CE" },
  LA:    { bg: "#FFF1F2", text: "#9F1239" },
};

function RegimeBadge({ regime }: { regime: RegimeTributario }) {
  const s = REGIME_STYLE[regime] ?? REGIME_STYLE[""];
  return (
    <span
      className="inline-block rounded-md px-2 py-0.5 text-xs font-medium"
      style={{ background: s.bg, color: s.text }}
    >
      {regime ? REGIME_LABELS[regime] : "Regime não informado"}
    </span>
  );
}

function certStatus(cert: Certificado | undefined) {
  if (!cert) return null;
  const dias = daysUntil(cert.validade);
  if (!cert.ativo || dias <= 0) return { label: "Vencido", variant: "destructive" as const, dias };
  if (dias <= 7)  return { label: "Crítico", variant: "destructive" as const, dias };
  if (dias <= 30) return { label: "Vence em breve", variant: "warning" as const, dias };
  return { label: "Ativo", variant: "success" as const, dias };
}

function CarteiraPage() {
  const { isStaff } = useAuth();
  const [openCliente, setOpenCliente] = useState(false);
  const [certTarget, setCertTarget] = useState<number | undefined>();
  const [deleteTarget, setDeleteTarget] = useState<{ id: number; nome: string } | undefined>();
  const [regimeTarget, setRegimeTarget] = useState<{ id: number; nome: string; regime: RegimeTributario } | undefined>();

  const clientesQuery = useQuery({ queryKey: ["clientes"], queryFn: listClientes });
  const certsQuery = useQuery({ queryKey: ["certificados"], queryFn: listCertificados });

  if (!isStaff) return <Navigate to="/dashboard" replace />;

  const clientes = clientesQuery.data ?? [];
  const certs = certsQuery.data ?? [];

  const certMap = new Map<number, Certificado>();
  certs.forEach((c) => certMap.set(c.cliente, c));

  const certAtivos = certs.filter((c) => {
    const st = certStatus(c);
    return st && st.variant === "success";
  }).length;

  const loading = clientesQuery.isLoading || certsQuery.isLoading;

  return (
    <AppShell title="Carteira de Clientes" subtitle="Gerencie CNPJs e certificados digitais">
      <div className="space-y-5">
        <div className="flex items-center justify-between">
          <p className="text-sm text-muted-foreground">
            {loading
              ? "Carregando..."
              : `${clientes.length} CNPJ(s) na carteira · ${certAtivos} certificado(s) ativo(s)`}
          </p>
          <Button onClick={() => setOpenCliente(true)}>
            <Plus className="mr-2 h-4 w-4" />
            Novo Cliente
          </Button>
        </div>

        {loading ? (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="rounded-[14px] p-5" style={{ background: "#fff", border: "1px solid #F1F5F9" }}>
                <Skeleton className="h-5 w-3/4 mb-3" />
                <Skeleton className="h-4 w-1/2 mb-2" />
                <Skeleton className="h-4 w-2/3" />
              </div>
            ))}
          </div>
        ) : clientes.length === 0 ? (
          <div className="rounded-[14px] py-16 text-center text-sm text-muted-foreground" style={{ background: "#fff", border: "1px solid #F1F5F9" }}>
            Nenhum cliente cadastrado. Clique em "Novo Cliente" para começar.
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {clientes.map((c) => {
              const cert = certMap.get(c.id);
              const st = certStatus(cert);
              return (
                <div
                  key={c.id}
                  className="rounded-[14px] p-5 flex flex-col gap-3"
                  style={{ background: "#fff", border: "1px solid #F1F5F9" }}
                >
                  {/* Header */}
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="font-semibold text-sm leading-tight truncate" style={{ color: "#0F172A", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
                        {c.razao_social}
                      </p>
                      <p className="text-xs font-mono tabular-nums mt-0.5" style={{ color: "#94A3B8" }}>
                        {formatCnpj(c.cnpj)}
                      </p>
                    </div>
                    <span
                      className="shrink-0 text-xs font-semibold px-2.5 py-1 rounded-lg"
                      style={c.ativo === false
                        ? { background: "#F1F5F9", color: "#64748B" }
                        : { background: "#DCFCE7", color: "#15803D" }}
                    >
                      {c.ativo === false ? "Inativo" : "Ativo"}
                    </span>
                  </div>

                  {/* Regime tributário */}
                  <button
                    className="flex items-center gap-1.5 text-left group"
                    title="Clique para editar o regime tributário"
                    onClick={() => setRegimeTarget({ id: c.id, nome: c.razao_social, regime: c.regime_tributario })}
                  >
                    <RegimeBadge regime={c.regime_tributario} />
                    <Pencil className="h-3 w-3 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
                  </button>

                  {/* Cert info */}
                  <div
                    className="flex items-center gap-2.5 rounded-[10px] px-3 py-2.5"
                    style={{ background: "#F8FAFC", border: "1px solid #F1F5F9" }}
                  >
                    {st ? (
                      <>
                        {st.variant === "success" ? (
                          <ShieldCheck className="h-4 w-4 shrink-0" style={{ color: "#16A34A" }} />
                        ) : (
                          <ShieldAlert className="h-4 w-4 shrink-0" style={{ color: "#DC2626" }} />
                        )}
                        <div className="min-w-0 flex-1">
                          <p className="text-xs font-semibold" style={{ color: "#0F172A" }}>{st.label}</p>
                          {cert && (
                            <p className="text-xs" style={{ color: st.dias <= 7 ? "#DC2626" : "#94A3B8" }}>
                              Validade: {formatDate(cert.validade)}
                            </p>
                          )}
                        </div>
                      </>
                    ) : (
                      <>
                        <FileKey className="h-4 w-4 shrink-0" style={{ color: "#94A3B8" }} />
                        <p className="text-xs" style={{ color: "#94A3B8" }}>Certificado não cadastrado</p>
                      </>
                    )}
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2 pt-1">
                    <Button
                      variant="outline"
                      size="sm"
                      className="flex-1 text-xs"
                      onClick={() => setCertTarget(c.id)}
                    >
                      <Upload className="mr-1.5 h-3.5 w-3.5" />
                      {cert ? "Atualizar cert." : "Enviar cert."}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-destructive hover:text-destructive hover:bg-destructive/5"
                      onClick={() => setDeleteTarget({ id: c.id, nome: c.razao_social })}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <NovoClienteDialog open={openCliente} onOpenChange={setOpenCliente} />
      <EditarRegimeDialog
        target={regimeTarget}
        onOpenChange={(v) => { if (!v) setRegimeTarget(undefined); }}
      />
      <UploadCertDialog
        open={certTarget !== undefined}
        onOpenChange={(v) => {
          if (!v) setCertTarget(undefined);
        }}
        clienteId={certTarget}
      />
      <ConfirmarExclusaoDialog
        target={deleteTarget}
        onOpenChange={(v) => { if (!v) setDeleteTarget(undefined); }}
      />
    </AppShell>
  );
}

// ---- Confirmar Exclusão ----

function ConfirmarExclusaoDialog({
  target,
  onOpenChange,
}: {
  target: { id: number; nome: string } | undefined;
  onOpenChange: (v: boolean) => void;
}) {
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: () => deleteCliente(target!.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["clientes"] });
      queryClient.invalidateQueries({ queryKey: ["certificados"] });
      toast.success(`Cliente "${target!.nome}" removido com sucesso`);
      onOpenChange(false);
    },
    onError: (err: Error) =>
      toast.error(err.message || "Não foi possível excluir. Verifique se há documentos vinculados."),
  });

  return (
    <AlertDialog open={target !== undefined} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Excluir cliente?</AlertDialogTitle>
          <AlertDialogDescription>
            Você tem certeza que deseja excluir{" "}
            <span className="font-semibold text-foreground">{target?.nome}</span>? Esta ação não
            pode ser desfeita. Clientes com documentos ou certificados vinculados não podem ser
            excluídos.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={mutation.isPending}>Cancelar</AlertDialogCancel>
          <AlertDialogAction
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            disabled={mutation.isPending}
            onClick={(e) => {
              e.preventDefault();
              mutation.mutate();
            }}
          >
            {mutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Excluir
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

// ---- Editar Regime ----

function EditarRegimeDialog({
  target,
  onOpenChange,
}: {
  target: { id: number; nome: string; regime: RegimeTributario } | undefined;
  onOpenChange: (v: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [regime, setRegime] = useState<RegimeTributario>("");

  // sync when target changes
  if (target && regime !== target.regime) {
    setRegime(target.regime);
  }

  const mutation = useMutation({
    mutationFn: () => patchCliente(target!.id, { regime_tributario: regime }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["clientes"] });
      toast.success("Regime tributário atualizado");
      onOpenChange(false);
    },
    onError: (err: Error) => toast.error(err.message || "Falha ao atualizar regime"),
  });

  return (
    <Dialog open={target !== undefined} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Pencil className="h-4 w-4" />
            Regime Tributário
          </DialogTitle>
          <DialogDescription className="truncate">{target?.nome}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3 py-2">
          <Label>Selecione o regime</Label>
          <select
            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus:outline-none focus:ring-1 focus:ring-ring"
            value={regime}
            onChange={(e) => setRegime(e.target.value as RegimeTributario)}
          >
            {REGIME_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button disabled={mutation.isPending} onClick={() => mutation.mutate()}>
            {mutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Salvar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---- Novo Cliente ----

const REGIME_OPTIONS: { value: RegimeTributario; label: string }[] = [
  { value: "",    label: "Não informado" },
  { value: "MEI", label: "MEI — Microempreendedor Individual" },
  { value: "SN",  label: "Simples Nacional" },
  { value: "LP",  label: "Lucro Presumido" },
  { value: "LR",  label: "Lucro Real" },
  { value: "LA",  label: "Lucro Arbitrado" },
];

const clienteSchema = z.object({
  cnpj: z
    .string()
    .trim()
    .refine((v) => v.replace(/\D/g, "").length === 14, "CNPJ deve ter 14 dígitos"),
  razao_social: z.string().trim().min(2, "Informe a razão social").max(150),
  telefone: z.string().trim().max(20).optional(),
  regime_tributario: z.string().optional(),
});

function NovoClienteDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<NovoClienteInput>({ cnpj: "", razao_social: "", telefone: "", regime_tributario: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});

  function reset() {
    setForm({ cnpj: "", razao_social: "", telefone: "", regime_tributario: "" });
    setErrors({});
  }

  const mutation = useMutation({
    mutationFn: createCliente,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["clientes"] });
      toast.success("Cliente cadastrado com sucesso");
      onOpenChange(false);
      reset();
    },
    onError: (err: Error) => toast.error(err.message || "Falha ao cadastrar cliente"),
  });

  function update<K extends keyof NovoClienteInput>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const parsed = clienteSchema.safeParse(form);
    if (!parsed.success) {
      const fieldErrors: Record<string, string> = {};
      parsed.error.issues.forEach((i) => {
        fieldErrors[i.path[0] as string] = i.message;
      });
      setErrors(fieldErrors);
      return;
    }
    setErrors({});
    mutation.mutate({ ...parsed.data, cnpj: parsed.data.cnpj.replace(/\D/g, "") });
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        onOpenChange(v);
        if (!v) reset();
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <UserPlus className="h-5 w-5" />
            Novo Cliente
          </DialogTitle>
          <DialogDescription>Cadastre um novo CNPJ na carteira do escritório.</DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="grid gap-4 sm:grid-cols-2">
          <Field label="Razão Social" error={errors.razao_social} className="sm:col-span-2">
            <Input
              value={form.razao_social}
              onChange={(e) => update("razao_social", e.target.value)}
              placeholder="Empresa Exemplo LTDA"
            />
          </Field>
          <Field label="CNPJ" error={errors.cnpj}>
            <Input
              value={form.cnpj}
              onChange={(e) => update("cnpj", e.target.value)}
              placeholder="00.000.000/0000-00"
            />
          </Field>
          <Field label="Telefone" error={errors.telefone}>
            <Input
              value={form.telefone ?? ""}
              onChange={(e) => update("telefone", e.target.value)}
              placeholder="(11) 90000-0000"
            />
          </Field>

          <Field label="Regime Tributário" error={errors.regime_tributario} className="sm:col-span-2">
            <select
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus:outline-none focus:ring-1 focus:ring-ring"
              value={form.regime_tributario ?? ""}
              onChange={(e) => setForm((f) => ({ ...f, regime_tributario: e.target.value as RegimeTributario }))}
            >
              {REGIME_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </Field>

          <DialogFooter className="sm:col-span-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Cadastrar
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ---- Upload Cert ----

function UploadCertDialog({
  open,
  onOpenChange,
  clienteId,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  clienteId: number | undefined;
}) {
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [senha, setSenha] = useState("");
  const [showSenha, setShowSenha] = useState(false);

  const mutation = useMutation({
    mutationFn: createCertificado,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["certificados"] });
      toast.success("Certificado salvo com sucesso");
      onOpenChange(false);
      reset();
    },
    onError: () => toast.error("Falha ao salvar certificado"),
  });

  function reset() {
    setArquivo(null);
    setSenha("");
    setShowSenha(false);
    if (fileRef.current) fileRef.current.value = "";
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!arquivo) return toast.error("Selecione o arquivo .pfx");
    if (!senha) return toast.error("Informe a senha do certificado");
    if (!clienteId) return toast.error("Cliente não identificado");
    mutation.mutate({ cliente: clienteId, arquivo, senha });
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        onOpenChange(v);
        if (!v) reset();
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Enviar Certificado A1</DialogTitle>
          <DialogDescription>Selecione o arquivo .pfx e informe a senha.</DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label>Arquivo do certificado (.pfx)</Label>
            <input
              ref={fileRef}
              type="file"
              accept=".pfx,.p12"
              className="hidden"
              onChange={(e) => setArquivo(e.target.files?.[0] ?? null)}
            />
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              className="flex w-full items-center gap-3 rounded-lg border border-dashed bg-muted/30 px-4 py-3 text-left text-sm transition-colors hover:bg-muted/50"
            >
              <FileKey className="h-5 w-5 shrink-0 text-muted-foreground" />
              <span className={cn("truncate", !arquivo && "text-muted-foreground")}>
                {arquivo?.name || "Clique para selecionar o arquivo .pfx"}
              </span>
            </button>
          </div>

          <div className="space-y-2">
            <Label htmlFor="senha-cert-carteira">Senha do certificado</Label>
            <div className="relative">
              <Input
                id="senha-cert-carteira"
                type={showSenha ? "text" : "password"}
                value={senha}
                onChange={(e) => setSenha(e.target.value)}
                placeholder="••••••••"
                className="pr-10"
              />
              <button
                type="button"
                onClick={() => setShowSenha((v) => !v)}
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground hover:text-foreground"
                aria-label={showSenha ? "Ocultar senha" : "Mostrar senha"}
              >
                {showSenha ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>

          <div className="flex items-start gap-2 rounded-lg border border-accent/30 bg-accent/5 p-3 text-xs text-muted-foreground">
            <Lock className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
            <p>
              <span className="font-medium text-foreground">Segurança LGPD:</span> o certificado é
              criptografado em repouso e utilizado apenas para comunicação assinada com a SEFAZ.
              A senha nunca é exposta em texto puro.
            </p>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Salvar certificado
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Field({
  label,
  error,
  className,
  children,
}: {
  label: string;
  error?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={className}>
      <Label className="mb-1.5 block">{label}</Label>
      {children}
      {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
    </div>
  );
}
