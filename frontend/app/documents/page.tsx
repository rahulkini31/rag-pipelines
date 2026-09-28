"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  listDocuments,
  uploadDocuments,
  deleteDocument,
  bulkDeleteDocuments,
  renameDocument,
  shareDocument,
  DocumentItem,
  subscribeEvents,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { ProtectedLayout } from "@/components/protected-layout";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Checkbox } from "@/components/ui/checkbox";

export default function DocumentsPage() {
  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [renameDoc, setRenameDoc] = useState<DocumentItem | null>(null);
  const [newName, setNewName] = useState("");
  const [shareDoc, setShareDoc] = useState<DocumentItem | null>(null);
  const [recipient, setRecipient] = useState("");

  const fetchDocs = async () => {
    try {
      setLoading(true);
      const data = await listDocuments({ search });
      setDocs(data.items);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDocs();
    const unsubscribe = subscribeEvents((data) => {
      if (data?.type === "status_update") fetchDocs();
    });
    return () => unsubscribe();
  }, [search]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files?.length) return;
    try {
      setUploading(true);
      await uploadDocuments(files);
      fetchDocs();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleDelete = async (docId: string) => {
    try {
      await deleteDocument(docId);
      fetchDocs();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleBulkDelete = async () => {
    try {
      await bulkDeleteDocuments(Array.from(selected));
      setSelected(new Set());
      fetchDocs();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const toggleSelect = (docId: string) => {
    const next = new Set(selected);
    if (next.has(docId)) next.delete(docId);
    else next.add(docId);
    setSelected(next);
  };

  const handleRenameSubmit = async () => {
    if (!renameDoc || !newName) return;
    try {
      await renameDocument(renameDoc.doc_id, newName);
      setRenameDoc(null);
      fetchDocs();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleShareSubmit = async () => {
    if (!shareDoc || !recipient) return;
    try {
      await shareDocument(shareDoc.doc_id, recipient);
      setShareDoc(null);
      setRecipient("");
      fetchDocs();
    } catch (err: any) {
      setError(err.message);
    }
  };

  return (
    <ProtectedLayout>
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold">Documents</h1>
          <div className="flex items-center gap-2">
            <Input
              placeholder="Search files..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-64"
            />
            <input
              type="file"
              multiple
              accept="application/pdf"
              ref={fileInputRef}
              onChange={handleUpload}
              className="hidden"
            />
            <Button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
            >
              {uploading ? "Uploading..." : "Upload PDF"}
            </Button>
          </div>
        </div>

        {selected.size > 0 && (
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">
              {selected.size} selected
            </span>
            <Button variant="destructive" size="sm" onClick={handleBulkDelete}>
              Delete Selected
            </Button>
          </div>
        )}

        {error && (
          <div className="text-sm text-red-600 bg-red-50 p-3 rounded">
            {error}
          </div>
        )}

        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10"></TableHead>
                <TableHead>Filename</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Chunks</TableHead>
                <TableHead>Updated</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-8">
                    Loading...
                  </TableCell>
                </TableRow>
              ) : docs.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                    No documents found.
                  </TableCell>
                </TableRow>
              ) : (
                docs.map((doc) => (
                  <TableRow key={doc.doc_id}>
                    <TableCell>
                      <Checkbox
                        checked={selected.has(doc.doc_id)}
                        onCheckedChange={() => toggleSelect(doc.doc_id)}
                      />
                    </TableCell>
                    <TableCell>
                      <Link
                        href={`/documents/${doc.doc_id}`}
                        className="hover:underline"
                      >
                        {doc.filename}
                      </Link>
                    </TableCell>
                    <TableCell>
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
                    </TableCell>
                    <TableCell>{doc.chunk_count ?? 0}</TableCell>
                    <TableCell>
                      {new Date(doc.updated_at).toLocaleString()}
                    </TableCell>
                    <TableCell className="text-right space-x-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          setRenameDoc(doc);
                          setNewName(doc.filename);
                        }}
                      >
                        Rename
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          setShareDoc(doc);
                          setRecipient("");
                        }}
                      >
                        Share
                      </Button>
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => handleDelete(doc.doc_id)}
                      >
                        Delete
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </div>

      <AlertDialog open={!!renameDoc} onOpenChange={() => setRenameDoc(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Rename Document</AlertDialogTitle>
            <AlertDialogDescription>
              Enter a new filename for the document.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <Input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setRenameDoc(null)}>
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction onClick={handleRenameSubmit}>
              Save
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={!!shareDoc} onOpenChange={() => setShareDoc(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Share Document</AlertDialogTitle>
            <AlertDialogDescription>
              Enter the recipient tenant ID. They will get read-only access.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <Input
            value={recipient}
            onChange={(e) => setRecipient(e.target.value)}
            placeholder="recipient-tenant"
          />
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setShareDoc(null)}>
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction onClick={handleShareSubmit}>
              Share
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </ProtectedLayout>
  );
}
