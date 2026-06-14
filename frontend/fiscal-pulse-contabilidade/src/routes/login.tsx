import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { AlertCircle, Eye, EyeOff, Loader2, ReceiptText, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import { useAuth } from "@/lib/auth";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export const Route = createFileRoute("/login")({
  head: () => ({
    meta: [{ title: "Entrar — Fiscal Tracker" }],
  }),
  component: LoginPage,
});

function classifyError(err: unknown): string {
  if (!(err instanceof Error)) return "Ocorreu um erro inesperado. Tente novamente.";

  // 401 vem como "Request failed: 401" de http() em api.ts
  if (err.message.includes("401")) {
    return "Usuário ou senha inválidos. Verifique suas credenciais.";
  }

  // TypeError é lançado pelo próprio fetch quando não consegue conectar
  if (
    err instanceof TypeError ||
    err.message.toLowerCase().includes("fetch") ||
    err.message.toLowerCase().includes("network")
  ) {
    return "Não foi possível conectar ao servidor. Verifique sua conexão de rede e tente novamente.";
  }

  return err.message || "Ocorreu um erro inesperado. Tente novamente.";
}

function LoginPage() {
  const { login, isAuthenticated, isLoading } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      navigate({ to: "/dashboard", replace: true });
    }
  }, [isAuthenticated, isLoading, navigate]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(username.trim(), password);
      toast.success("Bem-vindo de volta!");
      navigate({ to: "/dashboard", replace: true });
    } catch (err) {
      setError(classifyError(err));
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
            Captura fiscal automática, sem dor de cabeça.
          </h1>
          <p className="text-sm leading-relaxed text-sidebar-foreground/70">
            Centralize a captura de NF-e, CT-e, NFS-e e NFC-e, monitore certificados digitais A1 e
            exporte pacotes de notas por competência em poucos cliques.
          </p>
          <div className="flex items-center gap-2 rounded-lg border border-sidebar-border bg-sidebar-accent/40 p-3 text-xs text-sidebar-foreground/70">
            <ShieldCheck className="h-4 w-4 shrink-0 text-accent" />
            Certificados criptografados e usados apenas em comunicação interna assinada (LGPD).
          </div>
        </div>

        <p className="text-xs text-sidebar-foreground/40">
          © {new Date().getFullYear()} Fiscal Tracker — Todos os direitos reservados.
        </p>
      </div>

      {/* Form panel */}
      <div className="flex items-center justify-center bg-background px-6 py-12">
        <div className="w-full max-w-sm space-y-8">
          {/* Logo mobile */}
          <div className="space-y-2 lg:hidden">
            <div className="flex items-center gap-2">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                <ReceiptText className="h-5 w-5" />
              </div>
              <span className="text-lg font-semibold">Fiscal Tracker</span>
            </div>
          </div>

          <div className="space-y-1">
            <h2 className="text-2xl font-semibold tracking-tight">Acessar painel</h2>
            <p className="text-sm text-muted-foreground">
              Entre com suas credenciais para continuar.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="username">Usuário</Label>
              <Input
                id="username"
                value={username}
                onChange={(e) => {
                  setUsername(e.target.value);
                  setError(null);
                }}
                placeholder="seu.usuario"
                autoComplete="username"
                required
                aria-invalid={!!error}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="password">Senha</Label>
              <div className="relative">
                <Input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => {
                    setPassword(e.target.value);
                    setError(null);
                  }}
                  placeholder="••••••••"
                  autoComplete="current-password"
                  required
                  className="pr-10"
                  aria-invalid={!!error}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground hover:text-foreground"
                  aria-label={showPassword ? "Ocultar senha" : "Mostrar senha"}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
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
              Entrar
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}
