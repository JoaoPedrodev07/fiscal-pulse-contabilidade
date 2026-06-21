import { useState, type ReactNode } from "react";
import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import {
  Download,
  FileText,
  LayoutDashboard,
  LogOut,
  Menu,
  BarChart2,
  Users,
} from "lucide-react";

import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTrigger, SheetTitle } from "@/components/ui/sheet";

interface NavItem {
  to: string;
  label: string;
  icon: typeof LayoutDashboard;
  staffOnly?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { to: "/dashboard",  label: "Dashboard",   icon: LayoutDashboard },
  { to: "/documentos", label: "Documentos",  icon: FileText },
  { to: "/relatorios", label: "Relatórios",  icon: BarChart2,  staffOnly: true },
  { to: "/captura",    label: "Capturar",    icon: Download,   staffOnly: true },
  { to: "/carteira",   label: "Clientes",    icon: Users,      staffOnly: true },
];

/* ── Logo CaptaFiscal ──────────────────────────────────────────────── */
function CaptaFiscalLogo({ size = 32 }: { size?: number }) {
  const h = Math.round((size * 44) / 40);
  return (
    <svg width={size} height={h} viewBox="0 0 40 44" xmlns="http://www.w3.org/2000/svg" aria-hidden>
      <path
        d="M20 2 L38 9 Q40 10 40 11.5 L40 25 Q40 38 20 44 Q0 38 0 25 L0 11.5 Q0 10 2 9 Z"
        fill="#2563EB"
      />
      <polyline
        points="10,23 16,29 30,16"
        fill="none"
        stroke="#fff"
        strokeWidth="2.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/* ── Sidebar content ──────────────────────────────────────────────── */
function SidebarContentInner({ onNavigate }: { onNavigate?: () => void }) {
  const { user, isStaff, logout } = useAuth();
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  const items = NAV_ITEMS.filter((i) => !i.staffOnly || isStaff);

  function handleLogout() {
    logout();
    navigate({ to: "/login", replace: true });
  }

  const displayName = user?.username ?? "Usuário";
  const initials = displayName
    .split(" ")
    .slice(0, 2)
    .map((w: string) => w[0])
    .join("")
    .toUpperCase();

  return (
    <div
      className="flex h-full flex-col overflow-y-auto"
      style={{ background: "#0B1220", color: "#CBD5E1" }}
    >
      {/* Logo */}
      <div className="flex items-center gap-2.5 px-6 py-6" style={{ borderBottom: "1px solid #1E293B" }}>
        <CaptaFiscalLogo size={32} />
        <span
          className="font-semibold text-white"
          style={{ fontFamily: "'Plus Jakarta Sans', sans-serif", fontSize: 15 }}
          translate="no"
        >
          CaptaFiscal
        </span>
      </div>

      {/* Nav */}
      <nav className="flex flex-col gap-1.5 flex-1 px-4 py-5">
        {items.map((item) => {
          const active = pathname.startsWith(item.to);
          return (
            <Link
              key={item.to}
              to={item.to}
              onClick={onNavigate}
              className={cn(
                "flex items-center gap-3 rounded-[10px] px-3 py-2.5 text-sm font-medium transition-colors",
                active
                  ? "text-white"
                  : "hover:text-white"
              )}
              style={
                active
                  ? { background: "#2563EB", color: "#fff" }
                  : { color: "#94A3B8" }
              }
              onMouseEnter={(e) => {
                if (!active) {
                  (e.currentTarget as HTMLElement).style.background = "rgba(255,255,255,0.04)";
                  (e.currentTarget as HTMLElement).style.color = "#CBD5E1";
                }
              }}
              onMouseLeave={(e) => {
                if (!active) {
                  (e.currentTarget as HTMLElement).style.background = "transparent";
                  (e.currentTarget as HTMLElement).style.color = "#94A3B8";
                }
              }}
            >
              <item.icon className="h-[18px] w-[18px] shrink-0" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* User + logout */}
      <div className="px-4 pb-5" style={{ borderTop: "1px solid rgba(255,255,255,0.1)" }}>
        <div className="flex items-center gap-3 px-3 py-3 mt-3">
          <div
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white"
            style={{ background: "#2563EB" }}
          >
            {initials}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-white">{displayName}</p>
            <p className="truncate text-xs" style={{ color: "#64748B" }}>
              {isStaff ? "Escritório Contábil" : "Cliente Final"}
            </p>
          </div>
        </div>
        <button
          onClick={handleLogout}
          className="mt-1 flex w-full items-center gap-3 rounded-[10px] px-3 py-2.5 text-sm font-medium transition-colors"
          style={{ color: "#64748B" }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLElement).style.background = "rgba(255,255,255,0.04)";
            (e.currentTarget as HTMLElement).style.color = "#CBD5E1";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLElement).style.background = "transparent";
            (e.currentTarget as HTMLElement).style.color = "#64748B";
          }}
        >
          <LogOut className="h-[18px] w-[18px] shrink-0" />
          Sair
        </button>
      </div>
    </div>
  );
}

/* ── AppShell ──────────────────────────────────────────────────────── */
export function AppShell({
  title,
  subtitle,
  headerRight,
  children,
}: {
  title: string;
  subtitle?: string;
  headerRight?: ReactNode;
  children: ReactNode;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="flex min-h-screen w-full" style={{ background: "#F8FAFC" }}>
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 hidden w-64 lg:block" style={{ borderRight: "1px solid #1E293B" }}>
        <SidebarContentInner />
      </aside>

      <div className="flex min-h-screen w-full flex-col lg:pl-64">
        {/* Top bar */}
        <header
          className="sticky top-0 z-20 flex items-center justify-between gap-4 px-8 py-5"
          style={{ background: "#fff", borderBottom: "1px solid #E2E8F0" }}
        >
          <div className="flex items-center gap-4">
            {/* Mobile menu trigger */}
            <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
              <SheetTrigger asChild>
                <Button variant="outline" size="icon" className="lg:hidden">
                  <Menu className="h-5 w-5" />
                </Button>
              </SheetTrigger>
              <SheetContent side="left" className="w-64 border-0 p-0">
                <SheetTitle className="sr-only">Menu de navegação</SheetTitle>
                <SidebarContentInner onNavigate={() => setMobileOpen(false)} />
              </SheetContent>
            </Sheet>

            <div>
              <h1
                className="font-bold leading-tight"
                style={{
                  fontFamily: "'Plus Jakarta Sans', sans-serif",
                  fontSize: 28,
                  color: "#0F172A",
                  margin: 0,
                }}
              >
                {title}
              </h1>
              {subtitle && (
                <p className="mt-0.5 text-sm" style={{ color: "#94A3B8" }}>
                  {subtitle}
                </p>
              )}
            </div>
          </div>

          {headerRight && <div className="flex items-center gap-3">{headerRight}</div>}
        </header>

        <main className="flex-1 px-8 py-8">{children}</main>
      </div>
    </div>
  );
}

/* ── Stat card helper (exported for pages to use) ──────────────────── */
export function StatCard({
  label,
  value,
  hint,
  hintColor = "#94A3B8",
  loading = false,
}: {
  label: string;
  value: string | null;
  hint?: string;
  hintColor?: string;
  loading?: boolean;
}) {
  return (
    <div
      className="rounded-[14px] p-5"
      style={{ background: "#fff", border: "1px solid #F1F5F9" }}
    >
      <div
        className="text-xs font-semibold uppercase tracking-wide"
        style={{ color: "#94A3B8", letterSpacing: "0.3px" }}
      >
        {label}
      </div>
      {loading || value === null ? (
        <div className="mt-2 h-8 w-20 animate-pulse rounded" style={{ background: "#F1F5F9" }} />
      ) : (
        <div
          className="mt-2 font-extrabold leading-tight"
          style={{
            fontFamily: "'Plus Jakarta Sans', sans-serif",
            fontSize: 32,
            color: "#0F172A",
          }}
        >
          {value}
        </div>
      )}
      {hint && (
        <div className="mt-1.5 text-xs" style={{ color: hintColor }}>
          {hint}
        </div>
      )}
    </div>
  );
}

/* ── StatusPill (dot + label) ──────────────────────────────────────── */
export function StatusPill({
  label,
  bg,
  color,
}: {
  label: string;
  bg: string;
  color: string;
}) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold"
      style={{ background: bg, color }}
    >
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ background: "currentColor", opacity: 0.8 }}
      />
      {label}
    </span>
  );
}
