"use client";

import { useEffect, useState } from "react";
import { getTelemetrySummary } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ProtectedLayout } from "@/components/protected-layout";

export default function TelemetryPage() {
  const [summary, setSummary] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getTelemetrySummary().then(setSummary).catch((err) => setError(err.message));
  }, []);

  return (
    <ProtectedLayout>
      <div className="space-y-4">
        <h1 className="text-2xl font-semibold">Telemetry</h1>
        {error && (
          <div className="text-sm text-red-600 bg-red-50 p-3 rounded">{error}</div>
        )}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Total Documents</CardTitle>
            </CardHeader>
            <CardContent className="text-3xl font-bold">
              {summary?.total_documents ?? 0}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Successful</CardTitle>
            </CardHeader>
            <CardContent className="text-3xl font-bold text-green-600">
              {summary?.successful_ingestions ?? 0}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Failed</CardTitle>
            </CardHeader>
            <CardContent className="text-3xl font-bold text-red-600">
              {summary?.failed_ingestions ?? 0}
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Phoenix Traces</CardTitle>
          </CardHeader>
          <CardContent>
            <iframe
              src="http://localhost:6006"
              className="w-full h-[600px] border rounded"
              title="Phoenix"
            />
          </CardContent>
        </Card>
      </div>
    </ProtectedLayout>
  );
}
