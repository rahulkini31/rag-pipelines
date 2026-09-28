"use client";

import { useCallback, useEffect, useState } from "react";
import {
  runRanx,
  runRagasGenerate,
  runRagasEvaluate,
  runTrulens,
  listEvalHistory,
  getEvalResult,
  type EvalHistoryItem,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ProtectedLayout } from "@/components/protected-layout";
import { Loader2, Play, RefreshCw, X } from "lucide-react";

type EvalType = "ranx" | "ragas_generate" | "ragas_evaluate" | "trulens";

interface RunState {
  loading: boolean;
  result: Record<string, unknown> | null;
  error: string | null;
}

type Runner = (payload: Record<string, unknown>) => Promise<unknown>;

interface EvalConfig {
  label: string;
  description: string;
  defaultPayload: Record<string, unknown>;
  runner: Runner;
}

const EVAL_CONFIGS: Record<EvalType, EvalConfig> = {
  ranx: {
    label: "Ranx",
    description: "Retrieval benchmark: BM25 vs Dense vs Hybrid",
    defaultPayload: { queries: {}, qrels: {}, top_k: 10 },
    runner: runRanx,
  },
  ragas_generate: {
    label: "Ragas Generate",
    description: "Build a synthetic testset from every document",
    defaultPayload: { testset_size: 10 },
    runner: runRagasGenerate,
  },
  ragas_evaluate: {
    label: "Ragas Evaluate",
    description: "Score retrieval precision/recall with Ragas",
    defaultPayload: { top_k: 5 },
    runner: runRagasEvaluate,
  },
  trulens: {
    label: "TruLens",
    description: "RAG quality: context relevance, groundedness, answer relevance",
    defaultPayload: { queries: [], app_name: "Docling_Qdrant_Hybrid_RAG", app_version: "v1_qwen3_768tok" },
    runner: runTrulens,
  },
};

const EVAL_TYPES = Object.keys(EVAL_CONFIGS) as EvalType[];

function emptyRunState(): RunState {
  return { loading: false, result: null, error: null };
}

function initialRunStates(): Record<EvalType, RunState> {
  return {
    ranx: emptyRunState(),
    ragas_generate: emptyRunState(),
    ragas_evaluate: emptyRunState(),
    trulens: emptyRunState(),
  };
}

function formatTs(ts: string): string {
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) {
    return ts;
  }
  return date.toLocaleString();
}

function LatestResultCard(props: { label: string; state: RunState }) {
  const errored = props.state.error !== null;
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-base">Latest result — {props.label}</CardTitle>
        <Badge variant={errored ? "destructive" : "default"}>{errored ? "Error" : "Completed"}</Badge>
      </CardHeader>
      <CardContent className="space-y-2">
        {props.state.error !== null && (
          <p className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">{props.state.error}</p>
        )}
        {props.state.result !== null && (
          <pre className="max-h-96 overflow-auto rounded-md bg-muted p-3 text-xs">
            {JSON.stringify(props.state.result, null, 2)}
          </pre>
        )}
      </CardContent>
    </Card>
  );
}

function HistoryList(props: {
  items: EvalHistoryItem[];
  loading: boolean;
  onOpen: (item: EvalHistoryItem) => void;
}) {
  if (props.loading) {
    return (
      <div className="flex justify-center py-8">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (props.items.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        No evaluation runs yet. Use the buttons above to run one — results are stored in S3 under evaluations/.
      </p>
    );
  }
  return (
    <ul className="divide-y rounded-md border">
      {props.items.map((item) => (
        <li key={item.eval_id}>
          <button
            type="button"
            onClick={() => props.onOpen(item)}
            className="flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left hover:bg-muted/60"
          >
            <span className="flex items-center gap-3">
              <span className="font-mono text-sm">{item.eval_type}</span>
              <Badge variant={item.status === "completed" ? "default" : "destructive"}>{item.status}</Badge>
            </span>
            <span className="text-xs text-muted-foreground">{formatTs(item.timestamp)}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function ResultDetail(props: { data: any; onClose: () => void }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between space-y-0">
        <div>
          <CardTitle className="text-base">{props.data.eval_type} — run details</CardTitle>
          <CardDescription>{formatTs(props.data.timestamp)}</CardDescription>
        </div>
        <Button variant="ghost" size="icon" onClick={props.onClose}>
          <X className="h-4 w-4" />
        </Button>
      </CardHeader>
      <CardContent>
        <pre className="max-h-96 overflow-auto rounded-md bg-muted p-3 text-xs">
          {JSON.stringify(props.data.result, null, 2)}
        </pre>
      </CardContent>
    </Card>
  );
}

export default function EvaluationsPage() {
  const [runStates, setRunStates] = useState<Record<EvalType, RunState>>(initialRunStates);
  const [lastType, setLastType] = useState<EvalType | null>(null);
  const [history, setHistory] = useState<EvalHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [detail, setDetail] = useState<any | null>(null);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const data = await listEvalHistory();
      setHistory(data.results || []);
    } catch (err: any) {
      console.error("Failed to load history:", err);
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  const runEval = useCallback(
    async (type: EvalType) => {
      const cfg = EVAL_CONFIGS[type];
      setRunStates((prev) => ({ ...prev, [type]: { loading: true, result: null, error: null } }));
      setLastType(type);
      try {
        const data = await cfg.runner(cfg.defaultPayload);
        setRunStates((prev) => ({
          ...prev,
          [type]: { loading: false, result: data as Record<string, unknown>, error: null },
        }));
        loadHistory();
      } catch (err: any) {
        setRunStates((prev) => ({
          ...prev,
          [type]: { loading: false, result: null, error: String(err?.message || err) },
        }));
      }
    },
    [loadHistory],
  );

  const openDetail = useCallback(async (item: EvalHistoryItem) => {
    try {
      const data = await getEvalResult(item.eval_id);
      setDetail(data);
    } catch (err: any) {
      console.error("Failed to load result:", err);
    }
  }, []);

  return (
    <ProtectedLayout>
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-semibold">Evaluations</h1>
          <p className="text-muted-foreground">Run evaluations against the full corpus; history is persisted in S3.</p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Run Evaluation</CardTitle>
            <CardDescription>Every run executes against all documents in your tenant.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-2 sm:grid-cols-2">
            {EVAL_TYPES.map((type) => {
              const cfg = EVAL_CONFIGS[type];
              const state = runStates[type];
              return (
                <Button
                  key={type}
                  variant="outline"
                  className="justify-start"
                  onClick={() => runEval(type)}
                  disabled={state.loading}
                >
                  {state.loading ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Play className="mr-2 h-4 w-4" />
                  )}
                  Run {cfg.label}
                </Button>
              );
            })}
          </CardContent>
        </Card>

        {lastType !== null && <LatestResultCard label={EVAL_CONFIGS[lastType].label} state={runStates[lastType]} />}

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <div>
              <CardTitle>Previous Evaluation Results</CardTitle>
              <CardDescription>Click a run to see its full stored details.</CardDescription>
            </div>
            <Button variant="outline" size="sm" onClick={loadHistory} disabled={historyLoading}>
              <RefreshCw className={historyLoading ? "mr-2 h-4 w-4 animate-spin" : "mr-2 h-4 w-4"} />
              Refresh
            </Button>
          </CardHeader>
          <CardContent>
            <HistoryList items={history} loading={historyLoading} onOpen={openDetail} />
          </CardContent>
        </Card>

        {detail !== null && <ResultDetail data={detail} onClose={() => setDetail(null)} />}
      </div>
    </ProtectedLayout>
  );
}
