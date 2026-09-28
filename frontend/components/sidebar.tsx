"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  FileText,
  Activity,
  BarChart3,
  Settings,
  LogOut,
  Terminal,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/components/auth-provider";
import { cn } from "@/lib/utils";

const nav = [
  { href: "/documents", label: "Documents", icon: FileText },
  { href: "/telemetry", label: "Telemetry", icon: Activity },
  { href: "/evaluations", label: "Evaluations", icon: BarChart3 },
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/console", label: "Console", icon: Terminal },
];

export function Sidebar() {
  const pathname = usePathname();
  const { logout, tenantId } = useAuth();

  return (
    <aside className="w-64 border-r bg-background flex flex-col h-screen sticky top-0">
      <div className="p-4 border-b">
        <h1 className="font-semibold text-lg">Hybrid RAG Cockpit</h1>
        {tenantId && (
          <p className="text-xs text-muted-foreground mt-1">Tenant: {tenantId}</p>
        )}
      </div>
      <nav className="flex-1 p-2 space-y-1">
        {nav.map((item) => {
          const Icon = item.icon;
          const active = pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                active
                  ? "bg-primary text-primary-foreground"
                  : "hover:bg-muted"
              )}
            >
              <Icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="p-4 border-t">
        <Button variant="outline" className="w-full" onClick={logout}>
          <LogOut className="h-4 w-4 mr-2" />
          Logout
        </Button>
      </div>
    </aside>
  );
}
