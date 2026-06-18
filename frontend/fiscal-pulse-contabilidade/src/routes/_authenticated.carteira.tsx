import { createFileRoute, Navigate } from "@tanstack/react-router";
import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Eye,
  EyeOff,
  FileKey,
  Loader2,
  Lock,
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
import { createCertificado, createCliente, deleteCliente, listCertificados, listClientes } from "@/lib/api";
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
import type { Certificado, NovoClienteInput } from "@/lib/types";
import { daysUntil, formatCnpj, formatDate } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/_authenticated/carteira")({
  head: () => ({ meta: [{ title: "Carteira de Clientes — Fiscal Tracker" }] }),
  component: CarteiraPage,
});

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
    <AppShell title="Carteira de Clientes">
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

        <Card>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Razão Social</TableHead>
                  <TableHead>CNPJ</TableHead>
                  <TableHead>Certificado A1</TableHead>
                  <TableHead>Validade do Cert.</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Ações</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {loading ? (
                  Array.from({ length: 5 }).map((_, i) => (
                    <TableRow key={i}>
                      <TableCell colSpan={6}>
                        <Skeleton className="h-6 w-full" />
                      </TableCell>
                    </TableRow>
                  ))
                ) : clientes.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={6}
                      className="py-12 text-center text-sm text-muted-foreground"
                    >
                      Nenhum cliente cadastrado. Clique em "Novo Cliente" para começar.
                    </TableCell>
                  </TableRow>
                ) : (
                  clientes.map((c) => {
                    const cert = certMap.get(c.id);
                    const st = certStatus(cert);
                    return (
                      <TableRow key={c.id}>
                        <TableCell className="font-medium">{c.razao_social}</TableCell>
                        <TableCell className="font-mono text-sm tabular-nums">
                          {formatCnpj(c.cnpj)}
                        </TableCell>
                        <TableCell>
                          {st ? (
                            <div className="flex items-center gap-1.5">
                              {st.variant === "success" ? (
                                <ShieldCheck className="h-4 w-4 text-success" />
                              ) : (
                                <ShieldAlert className="h-4 w-4 text-destructive" />
                              )}
                              <Badge variant={st.variant}>{st.label}</Badge>
                            </div>
                          ) : (
                            <span className="text-xs text-muted-foreground">Não cadastrado</span>
                          )}
                        </TableCell>
                        <TableCell className="text-sm">
                          {cert ? (
                            <span className={cn(st && st.dias <= 0 && "text-destructive")}>
                              {formatDate(cert.validade)}
                            </span>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </TableCell>
                        <TableCell>
                          <Badge variant={c.ativo === false ? "secondary" : "success"}>
                            {c.ativo === false ? "Inativo" : "Ativo"}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setCertTarget(c.id)}
                            >
                              <Upload className="mr-1.5 h-4 w-4" />
                              {cert ? "Atualizar" : "Enviar"}
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="text-destructive hover:text-destructive"
                              onClick={() => setDeleteTarget({ id: c.id, nome: c.razao_social })}
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </div>
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

      <NovoClienteDialog open={openCliente} onOpenChange={setOpenCliente} />
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

// ---- Novo Cliente ----

const clienteSchema = z.object({
  cnpj: z
    .string()
    .trim()
    .refine((v) => v.replace(/\D/g, "").length === 14, "CNPJ deve ter 14 dígitos"),
  razao_social: z.string().trim().min(2, "Informe a razão social").max(150),
  telefone: z.string().trim().max(20).optional(),
});

function NovoClienteDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<NovoClienteInput>({ cnpj: "", razao_social: "", telefone: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});

  function reset() {
    setForm({ cnpj: "", razao_social: "", telefone: "" });
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
