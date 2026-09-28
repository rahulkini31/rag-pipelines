"use client";

import { useState, useRef, useEffect } from "react";
import { cn } from "@/lib/utils";

export function CloudShellProvider({ children }: { children: React.ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const [height, setHeight] = useState(300);
  const startY = useRef(0);
  const startHeight = useRef(0);

  const handleDragStart = (e: React.MouseEvent) => {
    startY.current = e.clientY;
    startHeight.current = height;
    document.addEventListener("mousemove", handleDrag);
    document.addEventListener("mouseup", handleDragEnd);
    e.preventDefault();
  };

  const handleDrag = (e: MouseEvent) => {
    const deltaY = startY.current - e.clientY;
    const newHeight = Math.max(150, Math.min(window.innerHeight * 0.8, startHeight.current + deltaY));
    setHeight(newHeight);
  };

  const handleDragEnd = () => {
    document.removeEventListener("mousemove", handleDrag);
    document.removeEventListener("mouseup", handleDragEnd);
  };

  useEffect(() => {
    return () => {
      document.removeEventListener("mousemove", handleDrag);
      document.removeEventListener("mouseup", handleDragEnd);
    };
  }, []);

  return (
    <>
      {children}
      {/* Console panel - fixed at bottom */}
      <div className="fixed bottom-0 left-0 right-0 z-50">
        <div
          className="fixed bottom-0 left-0 right-0 bg-gray-950 border-t border-gray-800 shadow-lg transition-all duration-300 z-50"
          style={{ height: isOpen ? `${height}px` : "2.5rem" }}
        >
          {/* Drag handle / toggle bar - always visible */}
          <div
            className="flex items-center justify-between p-2 border-b border-gray-800 cursor-ns-resize bg-gray-900 hover:bg-gray-800 select-none"
            onMouseDown={(e) => {
              startY.current = e.clientY;
              startHeight.current = height;
              document.addEventListener("mousemove", handleDrag);
              document.addEventListener("mouseup", handleDragEnd);
              e.preventDefault();
            }}
            onClick={() => setIsOpen(!isOpen)}
            style={{ cursor: "ns-resize" }}
          >
            <div className="flex items-center gap-2">
              <svg className="h-4 w-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" /></svg>
              <span className="text-xs font-medium text-green-300">CloudShell</span>
              <span className="px-2 py-0.5 text-xs bg-gray-800 rounded text-green-400">LIVE</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-500">
                {isOpen ? `Height: ${height}px` : "Click to expand"}
              </span>
              <button
                onClick={(e) => { e.stopPropagation(); setIsOpen(!isOpen); }}
                className="h-6 w-6 p-0 rounded hover:bg-gray-800"
              >
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={isOpen ? "M5 15l7-7 7 7" : "M19 9l-7 7-7-7"} /></svg>
              </button>
            </div>
          </div>

          {/* Console content - only rendered when open */}
          {isOpen && (
            <div style={{ height: `calc(100% - 2.5rem)` }} className="relative">
              <ConsoleContent height={height} />
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function ConsoleContent({ height }: { height: number }) {
  const [CloudShell, setCloudShell] = useState<any>(null);

  useEffect(() => {
    import("@/components/cloudshell").then((mod) => {
      setCloudShell(mod.CloudShell);
    });
  }, []);

  if (!CloudShell) return null;

  return <CloudShell height={height} />;
}