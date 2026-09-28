"use client";

import { CloudShell } from "@/components/cloudshell";
import { ProtectedLayout } from "@/components/protected-layout";

export default function ConsolePage() {
  return (
    <ProtectedLayout>
      <div className="h-screen">
        <CloudShell />
      </div>
    </ProtectedLayout>
  );
}