import { createFileRoute, Navigate } from "@tanstack/react-router";

export const Route = createFileRoute("/_authenticated/clientes")({
  component: () => <Navigate to="/carteira" replace />,
});
