"use client";

import React, { useEffect, useState, useRef, useCallback } from "react";
import Script from "next/script";
import { SeedTableDefinition } from "@/lib/api";
import { Play, RotateCcw, Database, Table, AlertCircle, Terminal } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";

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

  useEffect(() => {
    if (seedTables && seedTables.length > 0 && !activeTableTab) {
      setActiveTableTab(seedTables[0].name);
    }
  }, [seedTables, activeTableTab]);

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

      if (!SQL) return;

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
      if (isMounted) {
        setInitError(err.message || "Failed to initialize SQLite database engine.");
        setLoading(false);
      }
    }
    return () => {
      isMounted = false;
    };
  }, [seedTables]);

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
      <div className="flex flex-col gap-5 w-full my-6 text-zinc-100">
        {/* Table Schema Selector */}
        <Card variant="subtle" className="p-4 space-y-3">
          <div className="flex items-center gap-2 text-xs font-bold text-cyan-400 uppercase tracking-wider">
            <Database size={16} /> Seed Database Tables ({seedTables.length})
          </div>

          <div className="flex flex-wrap gap-2 border-b border-zinc-800 pb-3">
            {seedTables.map((table) => (
              <button
                key={table.name}
                onClick={() => setActiveTableTab(table.name)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                  activeTableTab === table.name
                    ? "bg-cyan-500/20 text-cyan-400 border border-cyan-500/40"
                    : "bg-zinc-800 text-zinc-400 hover:text-white border border-zinc-700/60"
                }`}
              >
                <Table size={14} />
                {table.name}
              </button>
            ))}
          </div>

          {selectedTable && (
            <div className="text-xs space-y-2">
              <div className="flex flex-wrap items-center gap-1.5 font-mono text-zinc-300">
                <span className="text-zinc-500 font-sans">Columns:</span>
                {selectedTable.columns.map((col, i) => (
                  <Badge key={i} variant="cyan" size="sm">
                    {col}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </Card>

        {/* Editor Area */}
        <Card variant="default" className="p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs font-bold text-cyan-400 uppercase tracking-wider">
              <Terminal size={16} /> Interactive SQL Query Console
            </div>
            <div className="flex items-center gap-2">
              <Button variant="secondary" size="sm" onClick={handleResetDb} disabled={loading} leftIcon={<RotateCcw size={12} />}>
                Reset DB
              </Button>
              <Button size="sm" onClick={handleRunQuery} disabled={loading || !db} leftIcon={<Play size={12} />}>
                Run Query (Ctrl+Enter)
              </Button>
            </div>
          </div>

          <div className="relative rounded-xl overflow-hidden border border-zinc-800 bg-zinc-950 font-mono text-xs">
            <textarea
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Enter SQL query (e.g. SELECT * FROM Movies;)"
              rows={4}
              className="w-full p-4 bg-transparent text-emerald-400 outline-none resize-y leading-relaxed font-mono placeholder:text-zinc-600 focus:ring-1 focus:ring-cyan-500"
              spellCheck={false}
            />
          </div>
        </Card>

        {/* Results Area */}
        <Card variant="subtle" className="p-4 space-y-3">
          <div className="flex items-center justify-between text-xs">
            <span className="font-semibold text-zinc-400 uppercase tracking-wider">Results</span>
            {executionTime !== null && <span className="text-zinc-500 font-mono">Executed in {executionTime} ms</span>}
          </div>

          {loading ? (
            <p className="text-xs text-zinc-400 animate-pulse">Loading in-browser SQLite WASM engine...</p>
          ) : queryError ? (
            <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-400 text-xs font-mono">
              <AlertCircle size={14} className="inline mr-1.5" />
              {queryError}
            </div>
          ) : queryResults && queryResults.length > 0 ? (
            queryResults.map((result, idx) => (
              <div key={idx} className="overflow-x-auto rounded-lg border border-zinc-800 bg-zinc-950">
                <table className="w-full text-left font-mono text-xs">
                  <thead className="bg-zinc-900 text-cyan-400 border-b border-zinc-800">
                    <tr>
                      {result.columns.map((col, cIdx) => (
                        <th key={cIdx} className="px-3 py-2 border-r last:border-r-0 border-zinc-800">
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-800/60">
                    {result.values.map((row, rIdx) => (
                      <tr key={rIdx} className="hover:bg-zinc-900/60">
                        {row.map((cell: any, cellIdx: number) => (
                          <td key={cellIdx} className="px-3 py-1.5 border-r last:border-r-0 border-zinc-800/60 text-zinc-300">
                            {cell === null ? <span className="text-zinc-600 italic">NULL</span> : String(cell)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))
          ) : (
            <p className="text-xs text-zinc-500 italic">Run a query to inspect SQL results.</p>
          )}
        </Card>
      </div>
    </>
  );
}
