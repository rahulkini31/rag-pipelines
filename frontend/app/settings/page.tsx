"use client";

import { useEffect, useState } from "react";
import { getConfig, updateConfig, validateConfig } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { ProtectedLayout } from "@/components/protected-layout";

const CONFIG_ORDER = [
  "qdrant_url",
  "qdrant_api_key",
  "aws_profile",
  "aws_region",
  "s3_bucket_name",
  "dynamodb_table_name",
  "featherless_api_key",
  "featherless_base_url",
  "featherless_model",
  "embedding_model",
  "judge_model",
  "cognito_user_pool_id",
  "cognito_client_id",
  "cognito_region",
];

export default function SettingsPage() {
  const [config, setConfig] = useState<Record<string, string | null>>({});
  const [edited, setEdited] = useState<Record<string, string>>({});
  const [reveal, setReveal] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  const fetchConfig = async () => {
    try {
      setLoading(true);
      const data = await getConfig(reveal);
      setConfig(data);
      setEdited(
        Object.fromEntries(CONFIG_ORDER.map((k) => [k, (data[k] as string) ?? ""]))
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchConfig();
  }, [reveal]);

  const handleSave = async () => {
    try {
      setSaving(true);
      const changed: Record<string, string> = {};
      CONFIG_ORDER.forEach((key) => {
        const original = config[key] ?? "";
        const current = edited[key] ?? "";
        if (current !== original && current !== "") {
          changed[key] = current;
        }
      });
      await updateConfig(changed);
      setMessage("Configuration saved to Secrets Manager.");
      fetchConfig();
    } catch (err: any) {
      setMessage(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleValidate = async () => {
    try {
      setMessage("Validating...");
      const result = await validateConfig();
      setMessage(JSON.stringify(result, null, 2));
    } catch (err: any) {
      setMessage(err.message);
    }
  };

  return (
    <ProtectedLayout>
      <div className="space-y-4 max-w-3xl">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold">Settings</h1>
          <Button variant="outline" onClick={() => setReveal((r) => !r)}>
            {reveal ? "Hide Secrets" : "Reveal Secrets"}
          </Button>
        </div>

        {message && (
          <div className="text-sm bg-muted p-3 rounded whitespace-pre-wrap">
            {message}
          </div>
        )}

        <Card>
          <CardHeader>
            <CardTitle>Runtime Configuration</CardTitle>
            <CardDescription>
              Values are stored in AWS Secrets Manager. Empty fields are not
              saved.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {loading ? (
              <p>Loading...</p>
            ) : (
              CONFIG_ORDER.map((key) => (
                <div key={key} className="space-y-2">
                  <Label htmlFor={key}>{key}</Label>
                  <Input
                    id={key}
                    type={reveal ? "text" : "password"}
                    value={edited[key] ?? ""}
                    onChange={(e) =>
                      setEdited((prev) => ({ ...prev, [key]: e.target.value }))
                    }
                    placeholder={config[key] ? "" : "Not set"}
                  />
                </div>
              ))
            )}
            <div className="flex gap-2 pt-4">
              <Button onClick={handleSave} disabled={saving || loading}>
                {saving ? "Saving..." : "Save Changes"}
              </Button>
              <Button variant="secondary" onClick={handleValidate} disabled={loading}>
                Validate Connections
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </ProtectedLayout>
  );
}
