"use client";

import React, { useEffect, useState, useRef, useCallback } from "react";
import Script from "next/script";
import { SeedTableDefinition } from "@/lib/api";
import { Play, RotateCcw, Database, Table, AlertCircle, CheckCircle2, Terminal } from "lucide-react";
import { Spinner } from "@/components/Spinner";

interface SqlRunnerProps {
  seedTables: SeedTableDefinition[];
  defaultQuery?: string;
}

export function SqlRunner({ seedTables, defaultQuery = "SELECT * FROM Movies;" }: SqlRunnerProps) {
  const [query, setQuery] = useState(defaultQuery);
  const [db, setDb] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [initError, setInitError] = useState("");
  const [queryError, setQueryError] = useState("");
  const [queryResults, setQueryResults] = useState<{ columns: string[]; values: any[][] }[] | null>(null);
  const [executionTime, setExecutionTime] = useState<number | null>(null);
  const [activeTableTab, setActiveTableTab] = useState<string>("");

  const sqlEngineRef = useRef<any>(null);

  // Initialize active table tab
  useEffect(() => {
    if (seedTables && seedTables.length > 0 && !activeTableTab) {
      setActiveTableTab(seedTables[0].name);
    }
  }, [seedTables, activeTableTab]);

  // Load sql.js WASM runtime
  const initDb = useCallback(async () => {
    let isMounted = true;
    try {
      setLoading(true);
      let SQL = sqlEngineRef.current;
      if (!SQL) {
        if ((window as any).initSqlJs) {
          SQL = await (window as any).initSqlJs({
            locateFile: (file: string) => `https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.8.0/${file}`,
          });
          sqlEngineRef.current = SQL;
        }
      }

      if (!SQL) {
        // If initSqlJs isn't ready yet, we retry in a moment or rely on Script onLoad
        return;
      }

      const newDb = new SQL.Database();
      if (seedTables && seedTables.length > 0) {
        for (const table of seedTables) {
          if (table.schema_sql) newDb.run(table.schema_sql);
          if (table.insert_sql) newDb.run(table.insert_sql);
        }
      }

      if (isMounted) {
        setDb(newDb);
        setLoading(false);
        setInitError("");
      }
    } catch (err: any) {
      console.error("SQL.js init error:", err);
      if (isMounted) {
        setInitError(err.message || "Failed to initialize client-side SQLite database engine.");
        setLoading(false);
      }
    }
    return () => {
      isMounted = false;
    };
  }, [seedTables]);

  // Try to init DB on mount (in case script was already loaded and cached)
  useEffect(() => {
    initDb();
  }, [initDb]);

  const handleResetDb = () => {
    if (!sqlEngineRef.current) return;
    try {
      const newDb = new sqlEngineRef.current.Database();
      for (const table of seedTables) {
        if (table.schema_sql) newDb.run(table.schema_sql);
        if (table.insert_sql) newDb.run(table.insert_sql);
      }
      setDb(newDb);
      setQueryResults(null);
      setQueryError("");
    } catch (err: any) {
      setQueryError("Failed to reset database: " + err.message);
    }
  };

  const handleRunQuery = () => {
    if (!db) return;
    setQueryError("");
    const startTime = performance.now();

    try {
      const results = db.exec(query);
      const endTime = performance.now();
      setExecutionTime(Math.round((endTime - startTime) * 100) / 100);
      setQueryResults(results);
    } catch (err: any) {
      setQueryError(err.message || String(err));
      setQueryResults(null);
      setExecutionTime(null);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      handleRunQuery();
    }
  };

  const selectedTable = seedTables.find((t) => t.name === activeTableTab) || seedTables[0];

  return (
    <>
      <Script 
        src="https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.8.0/sql-wasm.js" 
        strategy="lazyOnload" 
        onLoad={initDb}
      />
      <div className="flex flex-col gap-4 w-full">
      {/* Table Schema / Seed Data Inspector */}
      <div className="card-flat p-4 rounded-xl border border-line/60 bg-paper/80">
        <div className="flex items-center gap-2 mb-3 text-xs font-semibold text-teal uppercase tracking-wider">
          <Database size={16} /> Seed Database Tables ({seedTables.length})
        </div>

        {/* Table selector tabs */}
        <div className="flex flex-wrap gap-2 mb-3 border-b border-line/40 pb-2">
          {seedTables.map((table) => (
            <button
              key={table.name}
              onClick={() => setActiveTableTab(table.name)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                activeTableTab === table.name
                  ? "bg-teal/20 text-teal border border-teal/40 font-semibold"
                  : "bg-slate-800/60 text-gray-400 hover:text-white border border-line/30"
              }`}
            >
              <Table size={14} />
              {table.name}
            </button>
          ))}
        </div>

        {/* Selected Table columns & sample preview */}
        {selectedTable && (
          <div className="text-xs">
            <div className="flex flex-wrap items-center gap-1.5 mb-2 font-mono text-gray-300">
              <span className="text-gray-400 font-sans">Columns:</span>
              {selectedTable.columns.map((col, i) => (
                <span key={i} className="bg-slate-800 text-teal-light px-2 py-0.5 rounded border border-teal/20">
                  {col}
                </span>
              ))}
            </div>

            {/* Quick table data preview dropdown/container */}
            <details className="mt-2 text-gray-400 cursor-pointer">
              <summary className="hover:text-teal transition-colors font-medium">
                View {selectedTable.name} sample data ({selectedTable.rows.length} rows)
              </summary>
              <div className="mt-2 overflow-x-auto rounded-lg border border-line/40 bg-slate-900/80">
                <table className="w-full text-left font-mono text-[11px]">
                  <thead className="bg-slate-800/80 text-teal">
                    <tr>
                      {selectedTable.columns.map((c, i) => (
                        <th key={i} className="px-3 py-1.5 border-r last:border-r-0 border-line/30">
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {selectedTable.rows.slice(0, 5).map((row, rIdx) => (
                      <tr key={rIdx} className="border-b last:border-b-0 border-line/20 hover:bg-slate-800/40">
                        {row.map((cell: any, cIdx: number) => (
                          <td key={cIdx} className="px-3 py-1 border-r last:border-r-0 border-line/20">
                            {cell === null ? <span className="text-gray-500 italic">NULL</span> : String(cell)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </div>
        )}
      </div>

      {/* SQL Editor Area */}
      <div className="card-flat p-4 rounded-xl border border-line/60 bg-paper/90 shadow-md">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2 text-xs font-semibold text-teal uppercase tracking-wider">
            <Terminal size={16} /> Interactive SQL Query Editor
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleResetDb}
              disabled={loading}
              className="btn btn-sm btn-secondary flex items-center gap-1.5 text-xs py-1 px-2.5"
              title="Reset Database to original seed state"
            >
              <RotateCcw size={14} /> Reset DB
            </button>

            <button
              onClick={handleRunQuery}
              disabled={loading || !db}
              className="btn btn-sm btn-primary flex items-center gap-1.5 text-xs py-1 px-3"
            >
              <Play size={14} fill="currentColor" /> Run Query (Ctrl+Enter)
            </button>
          </div>
        </div>

        {/* Textarea Code Editor */}
        <div className="relative rounded-xl overflow-hidden border border-line/60 bg-slate-950 font-mono text-sm">
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Enter SQL query (e.g. SELECT * FROM Movies;)"
            rows={5}
            className="w-full p-4 bg-transparent text-emerald-400 outline-none resize-y leading-relaxed font-mono text-sm placeholder:text-gray-600"
            spellCheck={false}
          />
        </div>
      </div>

      {/* Query Results / Errors Output Area */}
      <div className="card-flat p-4 rounded-xl border border-line/60 bg-paper/80">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs font-semibold text-gray-300 uppercase tracking-wider">Query Results</span>
          {executionTime !== null && (
            <span className="text-xs text-gray-400 font-mono">Executed in {executionTime} ms</span>
          )}
        </div>

        {loading ? (
          <div className="flex items-center justify-center p-6 text-teal text-sm gap-2">
            <Spinner /> Loading in-browser SQLite database engine (sql.js)...
          </div>
        ) : initError ? (
          <div className="p-4 rounded-lg bg-red-950/40 border border-red-500/30 text-red-400 text-xs flex items-start gap-2">
            <AlertCircle size={16} className="mt-0.5 flex-shrink-0" />
            <div>
              <p className="font-semibold mb-1">Database Initialization Error</p>
              <p>{initError}</p>
            </div>
          </div>
        ) : queryError ? (
          <div className="p-4 rounded-lg bg-red-950/40 border border-red-500/30 text-red-400 text-xs flex items-start gap-2 font-mono">
            <AlertCircle size={16} className="mt-0.5 flex-shrink-0 text-red-400" />
            <div>
              <p className="font-semibold font-sans mb-1 text-red-300">SQL Error</p>
              <p>{queryError}</p>
            </div>
          </div>
        ) : queryResults && queryResults.length > 0 ? (
          queryResults.map((result, resIdx) => (
            <div key={resIdx} className="overflow-x-auto rounded-lg border border-line/60 bg-slate-950">
              <div className="px-3 py-1.5 bg-slate-900 text-xs text-teal font-mono border-b border-line/40 flex justify-between">
                <span>{result.values.length} row(s) returned</span>
              </div>
              <table className="w-full text-left font-mono text-xs">
                <thead className="bg-slate-900 text-teal-light font-semibold border-b border-line/40">
                  <tr>
                    {result.columns.map((col, cIdx) => (
                      <th key={cIdx} className="px-4 py-2 border-r last:border-r-0 border-line/30">
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.values.map((row, rIdx) => (
                    <tr key={rIdx} className="border-b last:border-b-0 border-line/20 hover:bg-slate-900/60 text-gray-200">
                      {row.map((cell: any, cellIdx: number) => (
                        <td key={cellIdx} className="px-4 py-2 border-r last:border-r-0 border-line/20">
                          {cell === null ? (
                            <span className="text-gray-500 italic font-sans">NULL</span>
                          ) : (
                            String(cell)
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))
        ) : queryResults && queryResults.length === 0 ? (
          <div className="p-4 text-center text-xs text-gray-400 bg-slate-900/50 rounded-lg border border-line/30">
            Query executed successfully. (0 rows returned or DDL/DML completed)
          </div>
        ) : (
          <div className="p-6 text-center text-xs text-gray-500 italic bg-slate-900/30 rounded-lg border border-line/30">
            Click &quot;Run Query&quot; to execute your SQL query against the in-memory SQLite database.
          </div>
        )}
      </div>
    </>
  );
}
