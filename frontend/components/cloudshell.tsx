"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { X, Pause, Play, Trash2, Filter, Loader2 } from "lucide-react";

interface LogEntry {
  id: number;
  timestamp: string;
  level: string;
  logger: string;
  message: string;
}

const LEVEL_COLORS: Record<string, string> = {
  DEBUG: "text-gray-500",
  INFO: "text-green-400",
  WARN: "text-yellow-400",
  WARNING: "text-yellow-400",
  ERROR: "text-red-400",
  CRITICAL: "text-red-600",
};

const LEVEL_BG: Record<string, string> = {
  DEBUG: "bg-gray-900/50",
  INFO: "bg-green-900/20",
  WARN: "bg-yellow-900/20",
  WARNING: "bg-yellow-900/20",
  ERROR: "bg-red-900/20",
  CRITICAL: "bg-red-900/30",
};

export function CloudShell({ height = 300 }: { height?: number }) {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [paused, setPaused] = useState(false);
  const [filter, setFilter] = useState("");
  const [levelFilter, setLevelFilter] = useState<string[]>(["DEBUG", "INFO", "WARN", "WARNING", "ERROR", "CRITICAL"]);
  const [connected, setConnected] = useState(false);
  const logIdRef = useRef(0);
  const eventSourceRef = useRef<EventSource | null>(null);
  const logsEndRef = useRef<HTMLDivElement>(null);
  const filterTimeoutRef = useRef<ReturnType<typeof setTimeout> | number | null>(null);

  const scrollToBottom = () => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [logs, paused]);

  useEffect(() => {
    const tenantId = localStorage.getItem("tenant_id") || "local-tenant";
    const token = localStorage.getItem("id_token");
    if (!token) return;

    const es = new EventSource(`http://localhost:8000/telemetry/console?tenant_id=${tenantId}`);
    eventSourceRef.current = es;

    es.onopen = () => {
      setConnected(true);
    };

    es.onerror = () => {
      setConnected(false);
      // EventSource auto-reconnects
    };

    es.addEventListener("console", (event) => {
      if (paused) return;
      try {
        const message = event.data;
        // Parse: [timestamp] LEVEL logger: message
        const match = message.match(/^\[(\d+)\]\s+(\w+)\s+([^:]+):\s*(.*)$/);
        if (match) {
          const [, ts, level, logger, message] = match;
          const date = new Date(parseInt(ts) * 1000);
          const timeStr = date.toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit", fractionalSecondDigits: 3 });
          setLogs((prev) => [...prev, { id: ++logIdRef.current, timestamp: timeStr, level, logger, message }]);
        } else {
          setLogs((prev) => [...prev, { id: ++logIdRef.current, timestamp: new Date().toLocaleTimeString(), level: "INFO", logger: "system", message }]);
        }
      } catch {
        setLogs((prev) => [...prev, { id: ++logIdRef.current, timestamp: new Date().toLocaleTimeString(), level: "INFO", logger: "system", message: event.data }]);
      }
    });

    es.addEventListener("heartbeat", () => {
      // Connection alive
    });

    return () => {
      es.close();
      eventSourceRef.current = null;
      setConnected(false);
    };
  }, [paused]);

  const filteredLogs = logs.filter((log) => {
    if (levelFilter.length > 0 && !levelFilter.includes(log.level)) return false;
    if (filter && !log.message.toLowerCase().includes(filter.toLowerCase()) && !log.logger.toLowerCase().includes(filter.toLowerCase())) return false;
    return true;
  });

  const clearLogs = () => {
    setLogs([]);
    logIdRef.current = 0;
  };

  const togglePause = () => setPaused((p) => !p);

  const handleFilterChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (filterTimeoutRef.current) clearTimeout(filterTimeoutRef.current);
    filterTimeoutRef.current = window.setTimeout(() => setFilter(e.target.value), 150);
  };

  return (
    <div className="flex flex-col h-full bg-black text-green-300 font-mono text-sm">
      {/* Toolbar */}
      <div className="flex items-center gap-2 p-2 border-b border-gray-800 bg-gray-950">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${connected ? "bg-green-500" : "bg-red-500"}`} />
          <span className="text-xs text-gray-400">CONSOLE</span>
        </div>

        <div className="flex-1" />

        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            onClick={togglePause}
            className={paused ? "bg-yellow-900/30" : ""}
            title={paused ? "Resume" : "Pause"}
          >
            {paused ? <Play className="h-4 w-4 text-yellow-400" /> : <Pause className="h-4 w-4" />}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={clearLogs}
            title="Clear"
          >
            <Trash2 className="h-4 w-4" />
          </Button>
          <div className="relative">
            <Filter className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-500" />
            <Input
              placeholder="Filter..."
              value={filter}
              onChange={handleFilterChange}
              className="w-48 pl-8 bg-gray-900 border-gray-700 text-xs"
            />
          </div>
          <div className="flex items-center gap-1">
            {["DEBUG", "INFO", "WARN", "ERROR"].map((lvl) => (
              <label key={lvl} className="flex items-center gap-1 cursor-pointer">
                <input
                  type="checkbox"
                  checked={levelFilter.includes(lvl)}
                  onChange={(e) => setLevelFilter((prev) => (e.target.checked ? [...prev, lvl] : prev.filter((l) => l !== lvl)))}
                  className="w-3 h-3 rounded border-gray-600 text-green-500 focus:ring-green-500"
                />
                <span className={`text-xs ${LEVEL_COLORS[lvl]}`}>{lvl}</span>
              </label>
            ))}
          </div>
        </div>
      </div>

      {/* Log output */}
      <div className="overflow-y-auto p-4 space-y-1" role="log" aria-live="polite" style={{ height: `calc(100% - 120px)` }}>
        {filteredLogs.length === 0 ? (
          <div className="text-gray-500 text-center py-8">
            {paused ? "Paused..." : "Waiting for logs..."}
          </div>
        ) : (
          <>
            {filteredLogs.map((log) => (
              <div
                key={log.id}
                className={`${LEVEL_BG[log.level]} px-2 py-0.5 rounded border-l-2 ${LEVEL_COLORS[log.level].replace("text-", "border-")} select-all`}
              >
                <span className="text-gray-500 mr-2">{log.timestamp}</span>
                <span className={`font-medium mr-2 ${LEVEL_COLORS[log.level]}`}>{log.level}</span>
                <span className="text-gray-400 mr-2">{log.logger}</span>
                <span className="text-gray-200 break-all">{log.message}</span>
              </div>
            ))}
            <div ref={logsEndRef} />
          </>
        )}
      </div>

      {/* Status bar */}
      <div className="px-2 py-1 text-xs text-gray-500 border-t border-gray-800 bg-gray-950 flex items-center justify-between">
        <span>{filteredLogs.length} / {logs.length} lines</span>
        <span className="text-xs text-gray-600">Auto-scroll: ON</span>
      </div>
    </div>
  );
}