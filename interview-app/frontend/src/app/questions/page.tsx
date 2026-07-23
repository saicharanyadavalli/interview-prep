"use client";

import React, { useEffect, useState, useRef, useCallback } from "react";
import { API } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { FilterBuilder } from "@/components/FilterBuilder";
import { Spinner } from "@/components/Spinner";
import { Search, ClipboardList } from "lucide-react";
import Link from "next/link";
import Image from "next/image";

const COMPANY_FILTER_OPTIONS = [
  "24*7 Innovation Labs", "ABCO", "Accenture", "Accolite", "Adobe", "Airtel", "Amazon", "Amdocs",
  "American Express", "Apple", "Arcesium", "Atlassian", "BankBazaar", "Belzabar", "Bloomberg",
  "Boomerang Commerce", "Brocade", "BrowserStack", "Cadence India", "Capgemini", "CarWale",
  "Cavisson System", "Cisco", "Citicorp", "Citrix", "Code Brew", "Codenation", "Cognizant",
  "CouponDunia", "D-E-Shaw", "Dailyhunt", "DE Shaw", "Dell", "Directi", "Drishti-Soft", "eBay",
  "Epic Systems", "Expedia", "Fab.com", "Facebook", "FactSet", "FiberLink", "Flipkart", "FreeCharge",
  "GE", "Goldman Sachs", "Google", "GreyOrange", "Grofers", "Groupon", "HCL", "Hike", "Housing.com",
  "HSBC", "Huawei", "IBM", "IgniteWorld", "Infinera", "InfoEdge", "Informatica", "Infosys", "InMobi",
  "Intel", "Intuit", "Jabong", "Juniper Networks", "JUSPAY", "KLA Tencor", "Knowlarity", "Komli Media",
  "Kritikal Solutions", "Kuliza", "Linkedin", "Lybrate", "Mahindra Comviva", "MakeMyTrip",
  "MAQ Software", "Media.net", "Medlife", "MetLife", "Microsoft", "Mobicip", "Monotype Solutions",
  "Moonfrog Labs", "Morgan Stanley", "Myntra", "Nagarro", "National Instruments", "nearbuy",
  "Netskope", "NPCI", "Nutanix", "Nvidia", "OATS Systems", "Ola Cabs", "One97", "Open Solutions",
  "Opera", "Oracle", "Oxigen Wallet", "OYO Rooms", "PayPal", "Paytm", "Payu", "Philips", "Polycom",
  "PropTiger", "Pubmatic", "Qualcomm", "Quikr", "redBus", "Rockstand", "Salesforce", "Samsung",
  "SAP Labs", "Sapient", "Service Now", "Snapdeal", "Sprinklr", "Streamoid Technologies", "Swiggy",
  "Synopsys", "Target Corporation", "Taxi4Sure", "TCS", "Tejas Network", "Teradata", "Tesco",
  "Times Internet", "TinyOwl", "Twitter", "Uber", "Unisys", "United Health Group", "Veritas", "Visa",
  "Vizury Interactive Solutions", "VMWare", "Walmart", "Wipro", "Wooker", "Xome", "Yahoo",
  "Yatra.com", "Yodlee Infotech", "Zillious", "Zoho", "Zomato", "Zopper", "Zycus"
];

const PAGE_SIZE = 100;
const UI_STATE_KEY = "questionsPageUiState";
const PAGE_CACHE_KEY = "questionsPageListCache";
const CUSTOM_FOLDER_KEY = "questionsCustomFolderV1";
const CACHE_TTL_MS = 15 * 60 * 1000;

function normalizeToken(t: any) {
  return String(t || "").trim().toLowerCase();
}

export default function QuestionsPage() {
  const { user } = useAuth();
  
  const [search, setSearch] = useState("");
  const [filterQuery, setFilterQuery] = useState<Record<string, any>>({ match: "all", status: [], difficulty: [], company: [], topic: [] });
  
  const [rows, setRows] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [isInitialLoad, setIsInitialLoad] = useState(true);
  const [errorMsg, setErrorMsg] = useState("");
  
  const [selectedQnum, setSelectedQnum] = useState<number | null>(null);
  const [suggestions, setSuggestions] = useState<any[]>([]);
  const [suggestionIndex, setSuggestionIndex] = useState(-1);
  const [showSuggestions, setShowSuggestions] = useState(false);
  
  const [hydratedTopics, setHydratedTopics] = useState<string[]>([]);
  
  const scrollerRef = useRef<HTMLElement>(null);
  const searchTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  
  const getRequestOptions = useCallback((currentOffset: number, currentLimit: number, q: string, filters: Record<string, any>) => {
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
  }, []);

  const getRequestCacheKey = useCallback((q: string, filters: Record<string, any>) => {
    const req = getRequestOptions(0, PAGE_SIZE, q, filters);
    return JSON.stringify({ q: req.q, solved: req.solved, filters: req.filters });
  }, [getRequestOptions]);

  const loadNextPage = useCallback(async (reset: boolean = false, currentSearch: string = search, currentFilters: Record<string, any> = filterQuery) => {
    setIsLoading(true);
    setErrorMsg("");
    
    let currentOffset = offset;
    let currentTotal = total;
    let currentRows = rows;
    
    if (reset) {
      currentOffset = 0;
      currentTotal = 0;
      currentRows = [];
      setOffset(0);
      setTotal(0);
      setRows([]);
      setHasMore(true);
      // Don't reset selectedQnum here so it persists across searches if possible, or maybe it should
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
      
      const combinedRows = [...currentRows, ...newRows];
      setRows(combinedRows);

      // Hydrate topics
      const discoveredTopics = Array.from(
        new Set(
          newRows
            .flatMap((row: any) => (Array.isArray(row.topic_tags) ? row.topic_tags : []))
            .map((item: any) => normalizeToken(item))
            .filter(Boolean)
        )
      ) as string[];
      if (discoveredTopics.length) {
        setHydratedTopics(prev => {
          const combined = new Set([...prev, ...discoveredTopics]);
          if (combined.size === prev.length) return prev;
          return Array.from(combined);
        });
      }
      
      if (!selectedQnum && combinedRows.length > 0) {
        setSelectedQnum(Number(combinedRows[0].qnum || 0));
      }
      
      // Save cache
      try {
        sessionStorage.setItem(
          PAGE_CACHE_KEY,
          JSON.stringify({
            key: getRequestCacheKey(currentSearch, currentFilters),
            rows: combinedRows,
            total: newTotal,
            offset: nextOffset,
            hasMore: more,
            selectedQnum: selectedQnum || (combinedRows.length ? Number(combinedRows[0].qnum) : null),
            scrollerTop: scrollerRef.current ? scrollerRef.current.scrollTop : window.scrollY,
            ts: Date.now(),
          })
        );
      } catch (_) {}
      
    } catch (err: any) {
      setErrorMsg(`Error: ${err.message}`);
    } finally {
      setIsLoading(false);
      setIsInitialLoad(false);
    }
  }, [offset, total, rows, selectedQnum, getRequestOptions, getRequestCacheKey]);

  // Initial Load & State Restoration
  useEffect(() => {
    let initialSearch = search;
    let initialQnum = selectedQnum;
    
    // Restore UI State
    try {
      const uiState = localStorage.getItem(UI_STATE_KEY);
      if (uiState) {
        const parsed = JSON.parse(uiState);
        if (typeof parsed.search === "string") {
          initialSearch = parsed.search;
          setSearch(initialSearch);
        }
        if (Number.isFinite(Number(parsed.selectedQnum))) {
          initialQnum = Number(parsed.selectedQnum);
          setSelectedQnum(initialQnum);
        }
      }
    } catch (_) {}

    // Check page cache
    let cacheValid = false;
    try {
      const cache = sessionStorage.getItem(PAGE_CACHE_KEY);
      if (cache) {
        const parsed = JSON.parse(cache);
        const age = Date.now() - Number(parsed.ts || 0);
        if (age <= CACHE_TTL_MS && String(parsed.key || "") === getRequestCacheKey(initialSearch, filterQuery)) {
          setRows(Array.isArray(parsed.rows) ? parsed.rows : []);
          setTotal(Number(parsed.total || 0));
          setOffset(Number(parsed.offset || 0));
          setHasMore(Boolean(parsed.hasMore));
          if (Number.isFinite(Number(parsed.selectedQnum))) {
            setSelectedQnum(Number(parsed.selectedQnum));
          }
          setTimeout(() => {
            if (scrollerRef.current) scrollerRef.current.scrollTop = Number(parsed.scrollerTop || 0);
          }, 100);
          cacheValid = true;
        }
      }
    } catch (_) {}

    if (!cacheValid) {
      loadNextPage(true, initialSearch, filterQuery);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Save UI state on changes
  useEffect(() => {
    try {
      localStorage.setItem(UI_STATE_KEY, JSON.stringify({
        search,
        selectedQnum,
        ts: Date.now()
      }));
    } catch (_) {}
  }, [search, selectedQnum]);

  // Handle Search Input (debounce)
  useEffect(() => {
    if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
    searchTimeoutRef.current = setTimeout(() => {
      // Re-fetch on search change if not mounting
      loadNextPage(true, search, filterQuery);
    }, 400);
    
    return () => {
      if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
    };
  }, [search]); // Intentionally omitting others

  const handleFilterChange = useCallback((state: any, queryObj: Record<string, any>) => {
    setFilterQuery(queryObj);
    loadNextPage(true, search, queryObj);
  }, [search, loadNextPage]);

  // Scroll listener for infinite scroll
  useEffect(() => {
    const handleScroll = () => {
      if (!hasMore || isLoading) return;
      const el = scrollerRef.current;
      if (el) {
        const remaining = el.scrollHeight - (el.scrollTop + el.clientHeight);
        if (remaining <= 190) {
          loadNextPage(false, search, filterQuery);
        }
      }
    };
    
    const el = scrollerRef.current;
    if (el) {
      el.addEventListener("scroll", handleScroll);
    }
    return () => {
      if (el) el.removeEventListener("scroll", handleScroll);
    };
  }, [hasMore, isLoading, loadNextPage, search, filterQuery]);

  // Suggestions logic
  useEffect(() => {
    const needle = normalizeToken(search);
    if (!needle || needle.length < 2) {
      setSuggestions([]);
      setShowSuggestions(false);
      return;
    }
    const scored = rows.map((row) => {
      const title = String(row.problem_name || "");
      const topic = (Array.isArray(row.topic_tags) ? row.topic_tags : []).join(" ");
      const companies = (Array.isArray(row.companies) ? row.companies : []).join(" ");
      const haystack = `${title} ${companies} ${topic} ${row.difficulty || ""}`.toLowerCase();
      const index = haystack.indexOf(needle);
      return { row, index, startsWithTitle: title.toLowerCase().startsWith(needle) };
    }).filter(item => item.index >= 0).sort((a, b) => {
      if (a.startsWithTitle !== b.startsWithTitle) return a.startsWithTitle ? -1 : 1;
      if (a.index !== b.index) return a.index - b.index;
      return Number(a.row.qnum || 0) - Number(b.row.qnum || 0);
    });
    
    setSuggestions(scored.slice(0, 7).map(item => item.row));
    setShowSuggestions(true);
  }, [search, rows]);

  // Derived state for selected question
  const selectedQuestion = rows.find(r => Number(r.qnum) === selectedQnum) || null;

  // Actions
  const addToCustomFolder = () => {
    if (!selectedQuestion) return alert("Select a question first.");
    try {
      const raw = localStorage.getItem(CUSTOM_FOLDER_KEY);
      const parsed = JSON.parse(raw || "[]");
      const existing = Array.isArray(parsed) ? parsed : [];
      const normalized = Array.from(new Set(existing.map((item) => Number(item || 0)).filter((v) => v > 0)));
      if (normalized.includes(Number(selectedQuestion.qnum))) {
        alert("Question already in custom folder.");
        return;
      }
      normalized.push(Number(selectedQuestion.qnum));
      localStorage.setItem(CUSTOM_FOLDER_KEY, JSON.stringify(normalized));
      alert("Added to custom folder.");
    } catch (_) {
      alert("Unable to save custom folder entry.");
    }
  };

  const addToRevisitQueue = async () => {
    if (!selectedQuestion) return alert("Select a question first.");
    try {
      await API.updateProgress(selectedQuestion.qnum, { revisit: true });
      alert("Added to revisit queue.");
    } catch (err: any) {
      alert(`Failed to add revisit: ${err.message}`);
    }
  };

  const estimateSuccessRate = (question: any) => {
    const diff = normalizeToken(question.difficulty);
    const base = diff === "easy" ? 82 : diff === "medium" ? 71 : diff === "hard" ? 59 : 70;
    const swing = Number(question.qnum || 0) % 11;
    return Math.max(42, Math.min(98, base + swing - 5));
  };

  return (
    <main className="main-content questions-main-content">
      <header className="page-header section" style={{ display: 'flex', justifyContent: 'space-between' }}>
        <h1 style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Image className="brand-logo" src="/assets/logo-mark.svg" alt="Logo" width={24} height={24} />
          <span>Interview Assistant</span>
          <span className="text-muted" style={{ fontSize: '0.9rem', fontWeight: 500, marginLeft: '0.5rem' }}>All Questions</span>
        </h1>
        <div className="page-header-actions">
          <span className="counter-badge">{rows.length} / {total}</span>
        </div>
      </header>

      <section className="questions-shell" style={{ display: 'flex', gap: '1.5rem', flexDirection: 'row' }}>
        {/* Left Side */}
        <div className="questions-left" style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
          
          {/* Search */}
          <div className="questions-search-wrap" style={{ position: 'relative' }}>
            <span style={{ position: 'absolute', left: '1rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--muted)', display: 'flex', alignItems: 'center' }}>
              <Search size={16} />
            </span>
            <input
              type="text"
              placeholder="Search questions, companies, difficulty..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onFocus={() => setShowSuggestions(true)}
              onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
              onKeyDown={(e) => {
                if (!showSuggestions || suggestions.length === 0) return;
                if (e.key === 'ArrowDown') {
                  e.preventDefault();
                  setSuggestionIndex((prev) => (prev + 1) % suggestions.length);
                } else if (e.key === 'ArrowUp') {
                  e.preventDefault();
                  setSuggestionIndex((prev) => (prev - 1 + suggestions.length) % suggestions.length);
                } else if (e.key === 'Enter' && suggestionIndex >= 0) {
                  e.preventDefault();
                  const row = suggestions[suggestionIndex];
                  setSearch(row.problem_name || "");
                  setSelectedQnum(Number(row.qnum));
                  setShowSuggestions(false);
                  setSuggestionIndex(-1);
                } else if (e.key === 'Escape') {
                  setShowSuggestions(false);
                  setSuggestionIndex(-1);
                }
              }}
              style={{ width: '100%', padding: '0.75rem 1rem 0.75rem 2.5rem', borderRadius: 'var(--radius)', border: '1px solid var(--line)', background: 'var(--paper)', color: 'var(--ink)' }}
            />
            {showSuggestions && suggestions.length > 0 && (
              <div className="questions-search-suggestions" style={{ position: 'absolute', top: '100%', left: 0, right: 0, background: 'var(--paper)', border: '1px solid var(--line)', borderRadius: 'var(--radius)', zIndex: 10, marginTop: '0.5rem', boxShadow: 'var(--shadow)' }}>
                {suggestions.map((row, i) => (
                  <button
                    key={i}
                    className={`questions-suggestion-item ${i === suggestionIndex ? "is-active" : ""}`}
                    style={{ 
                      display: 'flex', alignItems: 'center', gap: '0.5rem', width: '100%', padding: '0.75rem 1rem', 
                      background: i === suggestionIndex ? 'var(--sidebar-hover)' : 'transparent', 
                      border: 'none', borderBottom: '1px solid var(--line)', textAlign: 'left', cursor: 'pointer' 
                    }}
                    onClick={() => {
                      setSearch(row.problem_name || "");
                      setSelectedQnum(Number(row.qnum));
                      setShowSuggestions(false);
                      setSuggestionIndex(-1);
                    }}
                  >
                    <Search size={14} style={{ color: 'var(--muted)', flexShrink: 0 }} />
                    <span style={{ fontWeight: 500, color: 'var(--ink)' }}>{row.problem_name}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Filter */}
          <section aria-label="Question filters">
            <FilterBuilder 
              companies={COMPANY_FILTER_OPTIONS}
              topics={hydratedTopics}
              onChange={handleFilterChange}
            />
          </section>

          {/* List */}
          <section ref={scrollerRef} aria-label="Questions list" style={{ flex: 1, overflowY: 'auto', maxHeight: '600px', paddingRight: '0.5rem' }}>
            <div className="q-browse-list" style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {rows.length === 0 && !isLoading && !isInitialLoad && !errorMsg ? (
                <div className="empty-state" style={{ padding: '2rem', textAlign: 'center', background: 'var(--paper)', borderRadius: 'var(--radius)', border: '1px solid var(--line)' }}>
                  <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '0.5rem' }}>
                    <ClipboardList size={32} className="text-muted" />
                  </div>
                  <p className="text-muted">No questions found.</p>
                </div>
              ) : null}

              {rows.map((row) => (
                <div 
                  key={row.qnum} 
                  className={`q-browse-item ${selectedQnum === Number(row.qnum) ? "is-selected" : ""}`}
                  tabIndex={0}
                  style={{ 
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '1rem', 
                    background: selectedQnum === Number(row.qnum) ? 'var(--sidebar-active)' : 'var(--paper)', 
                    borderRadius: 'var(--radius)', border: '1px solid var(--line)', cursor: 'pointer'
                  }}
                  onClick={() => setSelectedQnum(Number(row.qnum))}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      setSelectedQnum(Number(row.qnum));
                    }
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', minWidth: 0 }}>
                    <span style={{ color: 'var(--muted)', fontSize: '0.85rem' }}>#{row.qnum}</span>
                    <span style={{ fontWeight: 600, color: 'var(--ink)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{row.problem_name}</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexShrink: 0 }}>
                    {row.solved === 1 && <span className="pill pill-solved" style={{ background: 'var(--green)', color: 'white', padding: '0.2rem 0.5rem', borderRadius: '4px', fontSize: '0.75rem' }}>Solved</span>}
                    <span className="pill" style={{ 
                      background: String(row.difficulty || '').toLowerCase() === 'easy' ? 'var(--green)' : 
                                  String(row.difficulty || '').toLowerCase() === 'medium' ? 'var(--amber)' : 
                                  String(row.difficulty || '').toLowerCase() === 'hard' ? 'var(--red)' : 'var(--sidebar-hover)', 
                      color: ['easy', 'medium', 'hard'].includes(String(row.difficulty || '').toLowerCase()) ? 'white' : 'inherit',
                      padding: '0.2rem 0.5rem', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600
                    }}>{row.difficulty}</span>
                    <span className="pill" style={{ background: 'var(--sidebar-hover)', padding: '0.2rem 0.5rem', borderRadius: '4px', fontSize: '0.75rem' }}>{estimateSuccessRate(row)}%</span>
                  </div>
                </div>
              ))}

              {isLoading && (
                <Spinner text="Loading questions..." />
              )}
              {errorMsg && (
                <div style={{ padding: '1rem', textAlign: 'center', color: 'var(--red)' }}>{errorMsg}</div>
              )}
              {!hasMore && rows.length > 0 && (
                <div style={{ padding: '1rem', textAlign: 'center', color: 'var(--muted)' }}>You have reached the end of the list.</div>
              )}
            </div>
          </section>
        </div>

        {/* Right Side / Preview Panel */}
        <aside className="questions-right" aria-label="Selected question details" style={{ width: '320px', flexShrink: 0, display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
          <article className="card-flat" style={{ padding: '1.5rem', background: 'var(--paper)', border: '1px solid var(--line)', borderRadius: 'var(--radius-lg)' }}>
            <h2 style={{ fontSize: '1.1rem', marginBottom: '0.5rem' }}>{selectedQuestion ? selectedQuestion.problem_name : "Select a question"}</h2>
            <p className="text-muted" style={{ fontSize: '0.9rem', lineHeight: 1.5 }}>
              {selectedQuestion ? 
                (selectedQuestion.statement_text ? selectedQuestion.statement_text.substring(0, 170) + "..." : "Open this question to view the full prompt.") 
                : "Choose a question from the list to see details."}
            </p>
          </article>

          <article className="card-flat" style={{ padding: '1.5rem', background: 'var(--paper)', border: '1px solid var(--line)', borderRadius: 'var(--radius-lg)' }}>
            <div style={{ marginBottom: '1rem', fontSize: '0.9rem' }}>
              <p style={{ marginBottom: '0.5rem' }}><strong style={{ color: 'var(--ink)' }}>Success Rate:</strong> <span style={{ color: 'var(--muted)' }}>{selectedQuestion ? `${estimateSuccessRate(selectedQuestion)}%` : "--"}</span></p>
              <p><strong style={{ color: 'var(--ink)' }}>Companies:</strong> <span style={{ color: 'var(--muted)' }}>{selectedQuestion ? (selectedQuestion.companies?.join(", ") || "General") : "--"}</span></p>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <button className="btn" type="button" disabled={!selectedQuestion} onClick={addToCustomFolder}>Add to Custom Folder</button>
              <button className="btn" type="button" disabled={!selectedQuestion} onClick={addToRevisitQueue}>Add to Revisit Queue</button>
              <Link 
                href={selectedQuestion ? `/solve?qnum=${encodeURIComponent(selectedQuestion.qnum)}` : "#"} 
                className="btn btn-primary" 
                style={{ pointerEvents: selectedQuestion ? 'auto' : 'none', opacity: selectedQuestion ? 1 : 0.5 }}
              >
                Open Question
              </Link>
            </div>
          </article>
        </aside>
      </section>
    </main>
  );
}
