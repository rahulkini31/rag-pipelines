"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { getDocument, getDocumentPreview } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ProtectedLayout } from "@/components/protected-layout";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export default function DocumentDetailPage() {
  const { id } = useParams();
  const [doc, setDoc] = useState<any>(null);
  const [preview, setPreview] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id) return;
    Promise.all([getDocument(id as string), getDocumentPreview(id as string)])
      .then(([docData, previewData]) => {
        setDoc(docData);
        setPreview(previewData);
      })
      .catch((err) => setError(err.message));
  }, [id]);

  return (
    <ProtectedLayout>
      <div className="space-y-4">
        {error && (
          <div className="text-sm text-red-600 bg-red-50 p-3 rounded">
            {error}
          </div>
        )}
        {doc && (
          <>
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-2xl font-semibold">{doc.filename}</h1>
                <div className="flex items-center gap-2 mt-2">
                  <Badge
                    variant={
                      doc.status === "ACTIVE"
                        ? "default"
                        : doc.status === "PROCESSING"
                        ? "secondary"
                        : "destructive"
                    }
                  >
                    {doc.status}
                  </Badge>
                  <span className="text-sm text-muted-foreground">
                    {doc.chunk_count ?? 0} chunks
                  </span>
                </div>
              </div>
              {doc.presigned_url && (
                <a href={doc.presigned_url} target="_blank" rel="noreferrer">
                  <Button>Open PDF</Button>
                </a>
              )}
            </div>

            <Tabs defaultValue="markdown">
              <TabsList>
                <TabsTrigger value="markdown">Docling Markdown</TabsTrigger>
                <TabsTrigger value="metadata">Metadata</TabsTrigger>
              </TabsList>
              <TabsContent value="markdown">
                <Card>
                  <CardContent className="pt-6">
                    <pre className="whitespace-pre-wrap text-sm font-mono">
                      {preview?.markdown || "Loading preview..."}
                    </pre>
                  </CardContent>
                </Card>
              </TabsContent>
              <TabsContent value="metadata">
                <Card>
                  <CardHeader>
                    <CardTitle>Document Metadata</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <pre className="text-sm">
                      {JSON.stringify(doc, null, 2)}
                    </pre>
                  </CardContent>
                </Card>
              </TabsContent>
            </Tabs>
          </>
        )}
      </div>
    </ProtectedLayout>
  );
}
