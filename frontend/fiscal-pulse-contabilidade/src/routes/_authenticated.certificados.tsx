import { createFileRoute, Navigate } from "@tanstack/react-router";

export const Route = createFileRoute("/_authenticated/certificados")({
  component: () => <Navigate to="/carteira" replace />,
});
