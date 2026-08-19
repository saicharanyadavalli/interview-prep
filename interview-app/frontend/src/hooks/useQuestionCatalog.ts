"use client";

import { useState, useCallback, useRef } from "react";
import { API } from "@/lib/api";

const PAGE_SIZE = 100;

function normalizeToken(t: any) {
  return String(t || "").trim().toLowerCase();
}

export function useQuestionCatalog() {
  const [search, setSearch] = useState("");
  const [filterQuery, setFilterQuery] = useState<Record<string, any>>({
    match: "all",
    status: [],
    difficulty: [],
    company: [],
    topic: [],
  });

  const [rows, setRows] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");
  const [selectedQnum, setSelectedQnum] = useState<number | null>(null);

  const getRequestOptions = useCallback(
    (currentOffset: number, currentLimit: number, q: string, filters: Record<string, any>) => {
      const safeTokens = Array.isArray(filters.status) ? filters.status.filter(Boolean) : [];
      let solvedMode = "all";
      if (safeTokens.length === 1) {
        const token = normalizeToken(safeTokens[0]);
        if (token === "solved" || token === "!unsolved") solvedMode = "solved";
        if (token === "unsolved" || token === "!solved") solvedMode = "unsolved";
      }

      return {
        q: q.trim(),
        solved: solvedMode,
        offset: currentOffset,
        limit: currentLimit,
        filters: { ...filters, status: [] },
      };
    },
    []
  );

  const fetchCatalog = useCallback(
    async (reset: boolean = false, currentSearch: string = search, currentFilters: Record<string, any> = filterQuery) => {
      setIsLoading(true);
      setErrorMsg("");

      let currentOffset = offset;
      let currentRows = rows;

      if (reset) {
        currentOffset = 0;
        currentRows = [];
        setOffset(0);
        setTotal(0);
        setRows([]);
        setHasMore(true);
      }

      try {
        const req = getRequestOptions(currentOffset, PAGE_SIZE, currentSearch, currentFilters);
        let data;
        try {
          data = await API.getAllQuestionsCatalogForUser(req);
        } catch (_) {
          data = await API.getAllQuestionsCatalog(req);
        }

        const newRows = (data.questions || []).map((item: any) => ({
          ...item,
          solved: Number(item.solved || 0),
        }));

        const newTotal = Number(data.total || 0);
        const nextOffset = currentOffset + newRows.length;
        const more = newRows.length === PAGE_SIZE && nextOffset < newTotal;

        setTotal(newTotal);
        setOffset(nextOffset);
        setHasMore(more);
        setRows([...currentRows, ...newRows]);
      } catch (err: any) {
        setErrorMsg(err.message || "Failed to load questions catalog.");
      } finally {
        setIsLoading(false);
      }
    },
    [offset, rows, search, filterQuery, getRequestOptions]
  );

  return {
    search,
    setSearch,
    filterQuery,
    setFilterQuery,
    rows,
    total,
    hasMore,
    isLoading,
    errorMsg,
    selectedQnum,
    setSelectedQnum,
    fetchCatalog,
  };
}
