"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";

const DEFAULT_TOPIC_OPTIONS = [
  "Advanced Data Structure", "Algorithms", "anagram", "Arrays", "AVL-Tree", "Backtracking",
  "BFS", "Binary Indexed Tree", "Binary Representation", "Binary Search", "Binary Search Tree",
  "Bit Magic", "circular linked list", "circular-linked-list", "Combinatorial", "constructive algo",
  "CPP", "Data Structures", "Deque", "Design-Pattern", "DFS", "Disjoint Set", "Divide and Conquer",
  "Division", "doubly-linked-list", "Dynamic Programming", "factorial", "Fibonacci", "Game Theory",
  "Geometric", "Graph", "Greedy", "Hash", "Heap", "implementation", "Java", "Java-Collections",
  "Kadane", "LCS", "Linked List", "logical-thinking", "Machine Learning", "Map", "Mathematical",
  "Matrix", "Merge Sort", "Misc", "Modular Arithmetic", "number-theory", "Numbers", "palindrome",
  "Pattern Searching", "pattern-printing", "permutation", "Practice-Problems", "prefix-sum",
  "Prime Number", "priority-queue", "Queue", "Recursion", "Regular Expression", "Searching",
  "Segment-Tree", "series", "set", "Shortest Path", "sieve", "sliding-window", "Sorting", "Stack",
  "STL", "Strings", "subset", "topological-sort", "Traversal", "Tree", "Trie", "two-pointer-algorithm",
  "union-find"
];

const FIELD_DEFS: Record<string, { label: string; values: string[] }> = {
  status: {
    label: "Status",
    values: ["solved", "unsolved"],
  },
  difficulty: {
    label: "Difficulty",
    values: ["easy", "medium", "hard"],
  },
  company: {
    label: "Company",
    values: [],
  },
  topic: {
    label: "Topics",
    values: [...DEFAULT_TOPIC_OPTIONS],
  },
};

function normalizeText(value: string | undefined | null) {
  return String(value || "").trim().toLowerCase();
}

function toLabel(value: string) {
  const text = String(value || "").trim();
  if (!text) return "";
  if (text.toLowerCase() === "unsolved") return "Not Solved";
  return text
    .split(" ")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export interface FilterCondition {
  field: string;
  operator: "is" | "is not";
  value: string;
}

export interface FilterState {
  version: number;
  matchType: "all" | "any";
  filters: FilterCondition[];
}

export interface FilterBuilderProps {
  storageKey?: string;
  persist?: boolean;
  onChange?: (state: FilterState, queryObj: Record<string, any>) => void;
  companies?: string[];
  topics?: string[];
}

export function FilterBuilder({
  storageKey = "questionsFilterBuilderState",
  persist = true,
  onChange,
  companies = [],
  topics = [],
}: FilterBuilderProps) {
  const [state, setState] = useState<FilterState>({
    version: 3,
    matchType: "all",
    filters: [],
  });
  const [isLoaded, setIsLoaded] = useState(false);

  const getCompanyLabels = useCallback(() => {
    const labels: Record<string, string> = {};
    companies.forEach((item) => {
      const raw = String(item || "").trim();
      const normalized = normalizeText(raw);
      if (normalized && !labels[normalized]) {
        labels[normalized] = raw;
      }
    });
    return labels;
  }, [companies]);

  const getTopicValues = useCallback(() => {
    const fromOptions = topics.map(normalizeText).filter(Boolean);
    const fallback = FIELD_DEFS.topic.values;
    const unique = new Set([...(fromOptions.length ? fromOptions : fallback)]);
    return Array.from(unique);
  }, [topics]);

  const getCompanyValues = useCallback(() => {
    const fromOptions = companies.map(normalizeText).filter(Boolean);
    const fallback = FIELD_DEFS.company.values;
    const unique = new Set([...(fromOptions.length ? fromOptions : fallback)]);
    return Array.from(unique);
  }, [companies]);

  const getValuesForField = useCallback(
    (field: string, currentValue?: string) => {
      const key = normalizeText(field);
      let vals: string[] = [];
      if (key === "topic") vals = getTopicValues();
      else if (key === "company") vals = getCompanyValues();
      else vals = FIELD_DEFS[key]?.values ? [...FIELD_DEFS[key].values] : [];

      if (currentValue) {
        const normalizedVal = normalizeText(currentValue);
        if (!vals.includes(normalizedVal)) {
          vals.unshift(normalizedVal);
        }
      }
      return vals;
    },
    [getTopicValues, getCompanyValues]
  );

  const toLabelForField = useCallback(
    (field: string, value: string) => {
      if (normalizeText(field) === "company") {
        const labels = getCompanyLabels();
        const exact = labels[normalizeText(value)];
        if (exact) return exact;
      }
      return toLabel(value);
    },
    [getCompanyLabels]
  );

  const sanitizeState = useCallback(
    (st: FilterState): FilterState => {
      const validMatch = st.matchType === "any" ? "any" : "all";
      const cleaned: FilterCondition[] = [];

      (st.filters || []).forEach((item) => {
        const field = normalizeText(item?.field);
        if (!FIELD_DEFS[field]) return;

        const operator = normalizeText(item.operator) === "is not" ? "is not" : "is";
        const value = normalizeText(item.value);
        const values = getValuesForField(field, value);
        if (!values.includes(value)) return;

        if (value) {
          cleaned.push({ field, operator, value });
        }
      });

      return { version: 3, matchType: validMatch, filters: cleaned };
    },
    [getValuesForField]
  );

  // Initial load
  useEffect(() => {
    let initialState: FilterState = { version: 3, matchType: "all", filters: [] };
    if (persist && typeof window !== "undefined") {
      try {
        const raw = localStorage.getItem(storageKey);
        if (raw) {
          const parsed = JSON.parse(raw);
          if (parsed && typeof parsed === "object") {
            const legacyDefaultOnly =
              !parsed.version &&
              Array.isArray(parsed.filters) &&
              parsed.filters.length === 1 &&
              normalizeText(parsed.filters[0]?.field) === "status" &&
              normalizeText(parsed.filters[0]?.operator) === "is" &&
              normalizeText(parsed.filters[0]?.value) === "strong";

            initialState = {
              version: 3,
              matchType: parsed.matchType === "any" ? "any" : "all",
              filters: legacyDefaultOnly ? [] : (Array.isArray(parsed.filters) ? parsed.filters : []),
            };
          }
        }
      } catch (e) {}
    }
    setState(sanitizeState(initialState));
    setIsLoaded(true);
  }, [persist, storageKey, sanitizeState]);

  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  const lastEmittedRef = useRef<string>("");

  // Handle updates & notify
  useEffect(() => {
    if (!isLoaded) return;
    const sanitized = sanitizeState(state);
    
    const queryObj: Record<string, any> = {
      match: sanitized.matchType,
      status: [],
      difficulty: [],
      company: [],
      topic: [],
    };

    sanitized.filters.forEach((item) => {
      const field = normalizeText(item.field);
      if (!queryObj[field]) return;
      const value = normalizeText(item.value);
      if (!value) return;
      const token = item.operator === "is not" ? `!${value}` : value;
      queryObj[field].push(token);
    });

    const currentStr = JSON.stringify(queryObj);
    if (currentStr === lastEmittedRef.current) return;
    lastEmittedRef.current = currentStr;

    if (persist && typeof window !== "undefined") {
      try {
        localStorage.setItem(storageKey, JSON.stringify(sanitized));
      } catch (e) {}
    }

    if (onChangeRef.current) {
      onChangeRef.current(sanitized, queryObj);
    }
  }, [state, isLoaded, persist, storageKey, sanitizeState]);

  const addFilter = () => {
    setState((prev) => ({
      ...prev,
      filters: [...prev.filters, { field: "status", operator: "is", value: "unsolved" }],
    }));
  };

  const removeFilter = (index: number) => {
    setState((prev) => ({
      ...prev,
      filters: prev.filters.filter((_, i) => i !== index),
    }));
  };

  const updateFilter = (index: number, key: keyof FilterCondition, value: string) => {
    setState((prev) => {
      const newFilters = [...prev.filters];
      const current = { ...newFilters[index] };

      if (key === "field") {
        const field = normalizeText(value);
        if (FIELD_DEFS[field]) {
          current.field = field;
          const values = getValuesForField(field);
          current.value = values[0] || "";
        }
      } else if (key === "operator") {
        current.operator = normalizeText(value) === "is not" ? "is not" : "is";
      } else if (key === "value") {
        current.value = normalizeText(value);
      }

      newFilters[index] = current;
      return { ...prev, filters: newFilters };
    });
  };

  const resetFilters = () => {
    setState({ version: 3, matchType: "all", filters: [] });
  };

  if (!isLoaded) return null;

  return (
    <div className="filter-builder-card">
      <div className="filter-builder-head">
        <span className="filter-head-label">Match</span>
        <select
          className="filter-builder-match"
          aria-label="Filter match type"
          value={state.matchType}
          onChange={(e) => setState({ ...state, matchType: e.target.value as "all" | "any" })}
        >
          <option value="all">All</option>
          <option value="any">Any</option>
        </select>
        <span className="filter-head-label">of the following filters</span>
        <span className="counter-badge filter-count-pill">{state.filters.length}</span>
      </div>

      <div className="filter-builder-rows">
        {state.filters.length === 0 ? (
          <p className="filter-builder-empty text-muted">No filters applied. Showing all questions.</p>
        ) : (
          state.filters.map((filter, index) => (
            <div key={index} className="filter-builder-row">
              <select
                className="filter-field"
                aria-label="Filter field"
                title="Field"
                value={filter.field}
                onChange={(e) => updateFilter(index, "field", e.target.value)}
              >
                {Object.keys(FIELD_DEFS).map((key) => (
                  <option key={key} value={key}>
                    {FIELD_DEFS[key].label}
                  </option>
                ))}
              </select>
              
              <select
                className="filter-operator"
                aria-label="Filter operator"
                value={filter.operator}
                onChange={(e) => updateFilter(index, "operator", e.target.value)}
              >
                <option value="is">is</option>
                <option value="is not">is not</option>
              </select>
              
              <select
                className="filter-value"
                aria-label="Filter value"
                title="Value"
                value={filter.value}
                onChange={(e) => updateFilter(index, "value", e.target.value)}
              >
                {getValuesForField(filter.field, filter.value).map((val) => (
                  <option key={val} value={val}>
                    {toLabelForField(filter.field, val)}
                  </option>
                ))}
              </select>
              
              <button
                type="button"
                className="btn btn-sm filter-remove"
                aria-label="Remove filter"
                title="Remove filter"
                onClick={() => removeFilter(index)}
              >
                Remove
              </button>
            </div>
          ))
        )}
      </div>

      <div className="filter-builder-actions">
        <button type="button" className="btn btn-sm" onClick={addFilter}>+ Add Filter</button>
        <button type="button" className="btn btn-sm" onClick={resetFilters}>Reset</button>
      </div>
    </div>
  );
}
