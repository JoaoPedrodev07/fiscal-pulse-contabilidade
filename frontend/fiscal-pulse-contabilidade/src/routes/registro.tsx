import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { AlertCircle, Building2, Eye, EyeOff, Loader2, ReceiptText } from "lucide-react";
import { toast } from "sonner";

import { registrarEscritorio } from "@/lib/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export const Route = createFileRoute("/registro")({
  head: () => ({ meta: [{ title: "Criar conta — Fiscal Tracker" }] }),
  component: RegistroPage,
});

function formatCnpj(raw: string) {
  const digits = raw.replace(/\D/g, "").slice(0, 14);
  return digits
    .replace(/^(\d{2})(\d)/, "$1.$2")
    .replace(/^(\d{2})\.(\d{3})(\d)/, "$1.$2.$3")
    .replace(/\.(\d{3})(\d)/, ".$1/$2")
    .replace(/(\d{4})(\d)/, "$1-$2");
}

function RegistroPage() {
  const navigate = useNavigate();

  const [razaoSocial, setRazaoSocial] = useState("");
  const [cnpj, setCnpj] = useState("");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [confirmar, setConfirmar] = useState("");
  const [showSenha, setShowSenha] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleCnpj(e: React.ChangeEvent<HTMLInputElement>) {
    setCnpj(formatCnpj(e.target.value));
    setError(null);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (senha !== confirmar) {
      setError("As senhas não coincidem.");
      return;
    }
    if (senha.length < 8) {
      setError("A senha deve ter pelo menos 8 caracteres.");
      return;
    }

    setSubmitting(true);
    try {
      await registrarEscritorio({
        razao_social: razaoSocial.trim(),
        cnpj: cnpj.replace(/\D/g, ""),
        username: username.trim(),
        email: email.trim(),
        senha,
        confirmar_senha: confirmar,
      });
      toast.success("Escritório cadastrado! Faça login para continuar.");
      navigate({ to: "/login" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao cadastrar. Tente novamente.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      {/* Brand panel */}
      <div className="relative hidden flex-col justify-between overflow-hidden bg-sidebar p-12 text-sidebar-foreground lg:flex">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-sidebar-primary text-sidebar-primary-foreground">
            <ReceiptText className="h-6 w-6" />
          </div>
          <div>
            <p className="text-lg font-semibold leading-tight">Fiscal Tracker</p>
            <p className="text-xs text-sidebar-foreground/60">Painel Fiscal</p>
          </div>
        </div>

        <div className="max-w-md space-y-5">
          <h1 className="text-3xl font-semibold leading-tight">
            Seu escritório conectado à SEFAZ em minutos.
          </h1>
          <p className="text-sm leading-relaxed text-sidebar-foreground/70">
            Cadastre seu escritório de contabilidade e comece a capturar NF-e, CT-e e NFS-e
            automaticamente para toda a sua carteira de clientes.
          </p>
          <div className="space-y-3 text-sm text-sidebar-foreground/70">
            {[
              "Captura automática a cada 1 hora",
              "Exportação em lote por competência",
              "Certificados A1 criptografados (LGPD)",
            ].map((item) => (
              <div key={item} className="flex items-center gap-2">
                <div className="h-1.5 w-1.5 rounded-full bg-accent" />
                {item}
              </div>
            ))}
          </div>
        </div>

        <p className="text-xs text-sidebar-foreground/40">
          © {new Date().getFullYear()} Fiscal Tracker — Todos os direitos reservados.
        </p>
      </div>

      {/* Form panel */}
      <div className="flex items-center justify-center bg-background px-6 py-12">
        <div className="w-full max-w-sm space-y-7">
          {/* Logo mobile */}
          <div className="flex items-center gap-2 lg:hidden">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <ReceiptText className="h-5 w-5" />
            </div>
            <span className="text-lg font-semibold">Fiscal Tracker</span>
          </div>

          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Building2 className="h-5 w-5 text-muted-foreground" />
              <h2 className="text-2xl font-semibold tracking-tight">Criar conta</h2>
            </div>
            <p className="text-sm text-muted-foreground">
              Dados do seu escritório de contabilidade.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Seção Escritório */}
            <div className="space-y-3 rounded-lg border border-border p-4">
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Escritório
              </p>

              <div className="space-y-2">
                <Label htmlFor="razao_social">Razão Social</Label>
                <Input
                  id="razao_social"
                  value={razaoSocial}
                  onChange={(e) => { setRazaoSocial(e.target.value); setError(null); }}
                  placeholder="Contabilidade ABC LTDA"
                  required
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="cnpj">CNPJ do Escritório</Label>
                <Input
                  id="cnpj"
                  value={cnpj}
                  onChange={handleCnpj}
                  placeholder="00.000.000/0000-00"
                  inputMode="numeric"
                  required
                />
              </div>
            </div>

            {/* Seção Acesso */}
            <div className="space-y-3 rounded-lg border border-border p-4">
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Acesso
              </p>

              <div className="space-y-2">
                <Label htmlFor="username">Usuário (login)</Label>
                <Input
                  id="username"
                  value={username}
                  onChange={(e) => { setUsername(e.target.value); setError(null); }}
                  placeholder="contabilidade.abc"
                  autoComplete="username"
                  required
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="email">E-mail</Label>
                <Input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => { setEmail(e.target.value); setError(null); }}
                  placeholder="contato@escritorio.com.br"
                  autoComplete="email"
                  required
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="senha">Senha</Label>
                <div className="relative">
                  <Input
                    id="senha"
                    type={showSenha ? "text" : "password"}
                    value={senha}
                    onChange={(e) => { setSenha(e.target.value); setError(null); }}
                    placeholder="Mínimo 8 caracteres"
                    autoComplete="new-password"
                    required
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

              <div className="space-y-2">
                <Label htmlFor="confirmar">Confirmar senha</Label>
                <Input
                  id="confirmar"
                  type={showSenha ? "text" : "password"}
                  value={confirmar}
                  onChange={(e) => { setConfirmar(e.target.value); setError(null); }}
                  placeholder="Repita a senha"
                  autoComplete="new-password"
                  required
                />
              </div>
            </div>

            {error && (
              <Alert variant="destructive" className="py-3">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Criar conta
            </Button>

            <p className="text-center text-sm text-muted-foreground">
              Já tem uma conta?{" "}
              <Link to="/login" className="font-medium text-primary hover:underline">
                Entrar
              </Link>
            </p>
          </form>
        </div>
      </div>
    </div>
  );
}
