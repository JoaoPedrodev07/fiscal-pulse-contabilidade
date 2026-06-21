import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { AlertCircle, Eye, EyeOff, Loader2, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import { useAuth } from "@/lib/auth";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

function CaptaFiscalLogo({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 80 80" xmlns="http://www.w3.org/2000/svg" aria-hidden>
      <rect width="80" height="80" rx="18" fill="#2563EB" />
      <polyline points="28,36 34,42 52,24" fill="none" stroke="#fff" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export const Route = createFileRoute("/login")({
  head: () => ({
    meta: [{ title: "Entrar — CaptaFiscal" }],
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
          <CaptaFiscalLogo size={36} />
          <div>
            <p className="text-lg font-semibold leading-tight" style={{ fontFamily: "'Plus Jakarta Sans', sans-serif" }} translate="no">
              Capta<span style={{ fontWeight: 800 }}>Fiscal</span>
            </p>
            <p className="text-xs" style={{ color: "rgba(203,213,225,0.6)" }}>Painel Fiscal</p>
          </div>
        </div>

        <div className="max-w-md space-y-5">
          <h1 className="text-3xl font-semibold leading-tight" style={{ fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
            Captura fiscal automática, sem dor de cabeça.
          </h1>
          <p className="text-sm leading-relaxed" style={{ color: "rgba(203,213,225,0.7)" }}>
            Centralize a captura de NF-e, CT-e, NFS-e e NFC-e, monitore certificados digitais A1 e
            exporte pacotes de notas por competência em poucos cliques.
          </p>
          <div
            className="flex items-center gap-2 rounded-xl p-3 text-xs"
            style={{ border: "1px solid #1E293B", background: "rgba(255,255,255,0.04)", color: "rgba(203,213,225,0.7)" }}
          >
            <ShieldCheck className="h-4 w-4 shrink-0" style={{ color: "#2563EB" }} />
            Certificados criptografados e usados apenas em comunicação interna assinada (LGPD).
          </div>
        </div>

        <p className="text-xs" style={{ color: "rgba(203,213,225,0.4)" }}>
          © {new Date().getFullYear()} CaptaFiscal — Todos os direitos reservados.
        </p>
      </div>

      {/* Form panel */}
      <div className="flex items-center justify-center bg-background px-6 py-12">
        <div className="w-full max-w-sm space-y-8">
          {/* Logo mobile */}
          <div className="space-y-2 lg:hidden">
            <div className="flex items-center gap-2.5">
              <CaptaFiscalLogo size={32} />
              <span className="text-lg font-semibold" style={{ fontFamily: "'Plus Jakarta Sans', sans-serif" }} translate="no">
                Capta<span style={{ fontWeight: 800 }}>Fiscal</span>
              </span>
            </div>
          </div>

          <div className="space-y-1">
            <h2 className="text-2xl font-semibold tracking-tight" style={{ fontFamily: "'Plus Jakarta Sans', sans-serif" }}>Acessar painel</h2>
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

            <p className="text-center text-sm text-muted-foreground">
              Novo no CaptaFiscal?{" "}
              <Link to="/registro" className="font-medium text-primary hover:underline">
                Criar conta
              </Link>
            </p>
          </form>
        </div>
      </div>
    </div>
  );
}
