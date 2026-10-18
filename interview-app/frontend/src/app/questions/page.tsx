"use client";

import React, { useEffect, useState, useRef, useCallback, Suspense, useMemo } from "react";
import { useSearchParams } from "next/navigation";
import { API } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { FilterBuilder } from "@/components/FilterBuilder";
import { Spinner } from "@/components/Spinner";
import {
  Search,
  ClipboardList,
  Play,
  X,
  RotateCcw,
  FolderPlus,
  CheckCircle2,
  Clock,
  Tag,
  Building2,
  Folder,
  FolderCheck,
  Check,
} from "lucide-react";
import Link from "next/link";
import Image from "next/image";
import { parseStatusFilterFromParams } from "@/utils/dashboard-navigation";
import { CustomFolderModal, CustomFolderItem } from "@/components/questions/CustomFolderModal";

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
const CUSTOM_FOLDERS_STORAGE_KEY = "questionsCustomFolders_v2";
const CACHE_TTL_MS = 15 * 60 * 1000;

const DEFAULT_FOLDERS: CustomFolderItem[] = [
  { name: "Favorites", qnums: [], count: 0 },
  { name: "Striver SDE Sheet", qnums: [], count: 0 },
  { name: "Must Revise", qnums: [], count: 0 },
];

function normalizeToken(t: any) {
  return String(t || "").trim().toLowerCase();
}

function QuestionsContent() {
  const { user } = useAuth();
  const searchParams = useSearchParams();

  const initialStatusFilter = useMemo(() => {
    return parseStatusFilterFromParams(searchParams);
  }, [searchParams]);

  const [search, setSearch] = useState("");
  const [filterQuery, setFilterQuery] = useState<Record<string, any>>(() => {
    const parsed = parseStatusFilterFromParams(searchParams);
    return {
      match: "all",
      status: parsed ? [parsed.value] : [],
      difficulty: [],
      company: [],
      topic: []
    };
  });

  const [rows, setRows] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [isInitialLoad, setIsInitialLoad] = useState(true);
  const [errorMsg, setErrorMsg] = useState("");

  // Preview Drawer & State
  const [selectedQnum, setSelectedQnum] = useState<number | null>(null);
  const [isPreviewClosed, setIsPreviewClosed] = useState(false);
  const isPreviewClosedRef = useRef(false);
  isPreviewClosedRef.current = isPreviewClosed;

  const [fetchedQuestion, setFetchedQuestion] = useState<any>(null);
  const [isLoadingQuestion, setIsLoadingQuestion] = useState(false);

  // Search Suggestions
  const [suggestions, setSuggestions] = useState<any[]>([]);
  const [suggestionIndex, setSuggestionIndex] = useState(-1);
  const [showSuggestions, setShowSuggestions] = useState(false);

  const [hydratedTopics, setHydratedTopics] = useState<string[]>([]);

  // Revisit State
  const [revisitSet, setRevisitSet] = useState<Set<number>>(new Set());
  const [isUpdatingRevisit, setIsUpdatingRevisit] = useState(false);

  // Custom Folders State
  const [folders, setFolders] = useState<CustomFolderItem[]>(DEFAULT_FOLDERS);
  const [isFolderModalOpen, setIsFolderModalOpen] = useState(false);

  // Toast Notification State
  const [toastMsg, setToastMsg] = useState("");
  const [toastType, setToastType] = useState<"info" | "success" | "error">("info");
  const [showToast, setShowToast] = useState(false);
  const toastTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const displayToast = useCallback((msg: string, type: "info" | "success" | "error" = "info") => {
    if (toastTimeoutRef.current) clearTimeout(toastTimeoutRef.current);
    setToastMsg(msg);
    setToastType(type);
    setShowToast(true);
    toastTimeoutRef.current = setTimeout(() => setShowToast(false), 2800);
  }, []);

  const scrollerRef = useRef<HTMLElement>(null);
  const searchTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const isSearchMountedRef = useRef(false);
  const isLoadingRef = useRef(false);
  isLoadingRef.current = isLoading;
  const hasMoreRef = useRef(true);
  hasMoreRef.current = hasMore;

  const handleClosePreview = useCallback(() => {
    setSelectedQnum(null);
    setIsPreviewClosed(true);
  }, []);

  const handleSelectQuestion = useCallback((qnum: number) => {
    setSelectedQnum(qnum);
    setIsPreviewClosed(false);
  }, []);

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
    return JSON.stringify({ userId: user?.id || "anon", q: req.q, solved: req.solved, filters: req.filters });
  }, [getRequestOptions, user?.id]);

  const loadNextPage = useCallback(async (reset: boolean = false, currentSearch: string = search, currentFilters: Record<string, any> = filterQuery) => {
    if (isLoadingRef.current && !reset) return;

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
    }

    try {
      const req = getRequestOptions(currentOffset, PAGE_SIZE, currentSearch, currentFilters);
      let data = await API.getAllQuestionsCatalogForUser(req);
      if (!data) {
        data = await API.getAllQuestionsCatalog(req);
      }

      const newRows = (data?.questions || []).map((item: any) => ({
        ...item,
        solved: Number(item.solved || 0),
      }));

      const newTotal = Number(data?.total || 0);
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

      // Auto-select first question ONLY on initial page load if user hasn't explicitly closed preview and no question is selected
      if (!selectedQnum && combinedRows.length > 0 && !isPreviewClosedRef.current && reset && isInitialLoad) {
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
            selectedQnum: isPreviewClosedRef.current ? null : (selectedQnum || (combinedRows.length ? Number(combinedRows[0].qnum) : null)),
            isPreviewClosed: isPreviewClosedRef.current,
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
  }, [offset, total, rows, selectedQnum, isInitialLoad, getRequestOptions, getRequestCacheKey, search, filterQuery]);

  // Initial Load & State Restoration
  useEffect(() => {
    let initialSearch = search;
    let initialQnum = selectedQnum;
    let restoredClosed = false;

    // Restore UI State
    try {
      const uiState = localStorage.getItem(UI_STATE_KEY);
      if (uiState) {
        const parsed = JSON.parse(uiState);
        if (typeof parsed.search === "string") {
          initialSearch = parsed.search;
          setSearch(initialSearch);
        }
        if (parsed.isPreviewClosed === true || parsed.selectedQnum === null) {
          restoredClosed = true;
          setIsPreviewClosed(true);
          setSelectedQnum(null);
          initialQnum = null;
        } else if (Number.isFinite(Number(parsed.selectedQnum))) {
          initialQnum = Number(parsed.selectedQnum);
          setSelectedQnum(initialQnum);
          setIsPreviewClosed(false);
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
          if (parsed.isPreviewClosed === true || parsed.selectedQnum === null) {
            setSelectedQnum(null);
            setIsPreviewClosed(true);
          } else if (Number.isFinite(Number(parsed.selectedQnum))) {
            setSelectedQnum(Number(parsed.selectedQnum));
            setIsPreviewClosed(false);
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
        isPreviewClosed,
        ts: Date.now()
      }));
    } catch (_) {}
  }, [search, selectedQnum, isPreviewClosed]);

  // Window Escape key listener to close question preview or folder modal
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (isFolderModalOpen) {
          setIsFolderModalOpen(false);
        } else if (selectedQnum !== null) {
          handleClosePreview();
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [selectedQnum, isFolderModalOpen, handleClosePreview]);

  // Load Custom Folders
  useEffect(() => {
    try {
      const stored = localStorage.getItem(CUSTOM_FOLDERS_STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed) && parsed.length > 0) {
          setFolders(parsed);
        }
      }
    } catch (_) {}

    API.getCustomFolders()
      .then((res) => {
        if (res && Array.isArray(res.folders) && res.folders.length > 0) {
          setFolders(res.folders);
          try {
            localStorage.setItem(CUSTOM_FOLDERS_STORAGE_KEY, JSON.stringify(res.folders));
          } catch (_) {}
        }
      })
      .catch(() => {});
  }, [user]);

  // Load Revisit Queue
  useEffect(() => {
    if (!user) {
      setRevisitSet(new Set());
      return;
    }
    API.getRevisitQueue()
      .then((res) => {
        const items = Array.isArray(res?.items) ? res.items : [];
        const qnums = items.map((it: any) => Number(it.qnum)).filter(Boolean);
        setRevisitSet(new Set(qnums));
      })
      .catch(() => {});
  }, [user]);

  // Sync revisit state updates from across app
  useEffect(() => {
    const handleRevisitUpdate = (e: any) => {
      const { qnum, revisit } = e.detail || {};
      if (qnum) {
        setRevisitSet((prev) => {
          const next = new Set(prev);
          if (revisit) next.add(Number(qnum));
          else next.delete(Number(qnum));
          return next;
        });
      }
    };
    window.addEventListener("ipp_revisit_updated", handleRevisitUpdate);
    return () => window.removeEventListener("ipp_revisit_updated", handleRevisitUpdate);
  }, []);

  // Handle Search Input (debounce, skipping initial mount to avoid duplicate fetch)
  useEffect(() => {
    if (!isSearchMountedRef.current) {
      isSearchMountedRef.current = true;
      return;
    }

    if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
    searchTimeoutRef.current = setTimeout(() => {
      loadNextPage(true, search, filterQuery);
    }, 400);

    return () => {
      if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
    };
  }, [search]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleFilterChange = useCallback((state: any, queryObj: Record<string, any>) => {
    setFilterQuery(queryObj);
    loadNextPage(true, search, queryObj);
  }, [search, loadNextPage]);

  // Scroll listener for infinite scroll
  useEffect(() => {
    const handleScroll = () => {
      if (!hasMoreRef.current || isLoadingRef.current) return;
      const el = scrollerRef.current;
      if (el) {
        const remaining = el.scrollHeight - (el.scrollTop + el.clientHeight);
        if (remaining <= 200) {
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
  }, [loadNextPage, search, filterQuery]);

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

  // Fetch full question if selectedQnum is not in loaded rows
  useEffect(() => {
    if (!selectedQnum) {
      setFetchedQuestion(null);
      return;
    }
    const found = rows.find(r => Number(r.qnum) === selectedQnum);
    if (found) {
      setFetchedQuestion(null);
    } else {
      setIsLoadingQuestion(true);
      API.getQuestionByQnum(String(selectedQnum)).then((res) => {
        if (res) setFetchedQuestion(res);
      }).catch(() => {}).finally(() => {
        setIsLoadingQuestion(false);
      });
    }
  }, [selectedQnum, rows]);

  // Also check individual question revisit status when selected
  useEffect(() => {
    if (!selectedQnum) return;
    API.getProgressStatus(String(selectedQnum))
      .then((res) => {
        if (res && typeof res.revisit === "boolean") {
          setRevisitSet((prev) => {
            const next = new Set(prev);
            if (res.revisit) next.add(selectedQnum);
            else next.delete(selectedQnum);
            return next;
          });
        }
      })
      .catch(() => {});
  }, [selectedQnum]);

  // Derived state for selected question
  const selectedQuestion = (selectedQnum ? rows.find(r => Number(r.qnum) === selectedQnum) : null) || fetchedQuestion || null;

  // Containing custom folders for selected question
  const containingFolders = useMemo(() => {
    if (!selectedQuestion) return [];
    const qnum = Number(selectedQuestion.qnum);
    return folders.filter((f) => f.qnums.includes(qnum));
  }, [selectedQuestion, folders]);

  // Revisit toggle action
  const toggleRevisit = async () => {
    if (!selectedQuestion || isUpdatingRevisit) return;
    const qnum = Number(selectedQuestion.qnum);
    const isCurrentlyRevisit = revisitSet.has(qnum);
    const nextState = !isCurrentlyRevisit;

    setIsUpdatingRevisit(true);
    setRevisitSet((prev) => {
      const next = new Set(prev);
      if (nextState) next.add(qnum);
      else next.delete(qnum);
      return next;
    });

    displayToast(
      nextState ? `Question #${qnum} added to revisit queue.` : `Question #${qnum} removed from revisit queue.`,
      "success"
    );

    try {
      await API.updateProgress(qnum, { revisit: nextState });
      window.dispatchEvent(
        new CustomEvent("ipp_revisit_updated", {
          detail: { qnum, revisit: nextState },
        })
      );
    } catch (err: any) {
      // Revert optimistic update
      setRevisitSet((prev) => {
        const next = new Set(prev);
        if (isCurrentlyRevisit) next.add(qnum);
        else next.delete(qnum);
        return next;
      });
      displayToast(`Failed to update revisit state: ${err.message}`, "error");
    } finally {
      setIsUpdatingRevisit(false);
    }
  };

  // Custom folder actions
  const handleAddToFolder = useCallback(
    async (folderName: string) => {
      if (!selectedQuestion) return { success: false, message: "Select a question first." };
      const qnum = Number(selectedQuestion.qnum);

      const targetFolder = folders.find((f) => f.name.toLowerCase() === folderName.toLowerCase());
      if (targetFolder && targetFolder.qnums.includes(qnum)) {
        return { success: true, alreadyPresent: true };
      }

      const updated = folders.map((f) => {
        if (f.name.toLowerCase() === folderName.toLowerCase()) {
          const nextQnums = Array.from(new Set([...f.qnums, qnum]));
          return { ...f, qnums: nextQnums, count: nextQnums.length };
        }
        return f;
      });

      setFolders(updated);
      try {
        localStorage.setItem(CUSTOM_FOLDERS_STORAGE_KEY, JSON.stringify(updated));
      } catch (_) {}

      displayToast(`Added Question #${qnum} to "${folderName}".`, "success");

      try {
        await API.addQuestionToFolder(folderName, qnum);
      } catch (_) {}

      return { success: true, alreadyPresent: false };
    },
    [selectedQuestion, folders, displayToast]
  );

  const handleCreateFolderAndAdd = useCallback(
    async (folderName: string) => {
      if (!selectedQuestion) return { success: false, message: "Select a question first." };
      const qnum = Number(selectedQuestion.qnum);
      const trimmed = folderName.trim();

      const existing = folders.find((f) => f.name.toLowerCase() === trimmed.toLowerCase());
      if (existing) {
        return handleAddToFolder(existing.name);
      }

      const newFolder: CustomFolderItem = {
        name: trimmed,
        qnums: [qnum],
        count: 1,
      };
      const updated = [...folders, newFolder];
      setFolders(updated);
      try {
        localStorage.setItem(CUSTOM_FOLDERS_STORAGE_KEY, JSON.stringify(updated));
      } catch (_) {}

      displayToast(`Created folder "${trimmed}" and added Question #${qnum}.`, "success");

      try {
        await API.createCustomFolder(trimmed, [qnum]);
      } catch (_) {}

      return { success: true, alreadyPresent: false };
    },
    [selectedQuestion, folders, handleAddToFolder, displayToast]
  );

  const estimateSuccessRate = (question: any) => {
    const diff = normalizeToken(question.difficulty);
    const base = diff === "easy" ? 82 : diff === "medium" ? 71 : diff === "hard" ? 59 : 70;
    const swing = Number(question.qnum || 0) % 11;
    return Math.max(42, Math.min(98, base + swing - 5));
  };

  const getDifficultyColor = (diff: string) => {
    const d = String(diff || '').toLowerCase();
    if (d === 'easy') return 'var(--green)';
    if (d === 'medium') return 'var(--amber)';
    if (d === 'hard') return 'var(--red)';
    return 'var(--sidebar-hover)';
  };

  const isSelectedRevisit = Boolean(selectedQuestion && revisitSet.has(Number(selectedQuestion.qnum)));

  return (
    <main className="main-content questions-main-content">
      {/* Toast Notification Container */}
      {showToast && (
        <div id="toast" className={`toast toast-${toastType} toast-show`}>
          {toastMsg}
        </div>
      )}

      <header className="page-header section" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <h1 style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Link
            href="/dashboard"
            className="header-brand-link"
            style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem', color: 'inherit', textDecoration: 'none' }}
            aria-label="Interview Assistant Dashboard"
            title="Interview Assistant - Go to Dashboard"
          >
            <Image className="brand-logo" src="/assets/logo-mark.svg" alt="Logo" width={24} height={24} />
            <span>Interview Assistant</span>
          </Link>
          <span className="text-muted" style={{ fontSize: '0.9rem', fontWeight: 500, marginLeft: '0.5rem' }}>Question Bank</span>
        </h1>
        <div className="page-header-actions" style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <span className="counter-badge" title="Loaded questions / Total in database">{rows.length} / {total}</span>
          {selectedQnum && (
            <button
              className="btn btn-sm"
              onClick={handleClosePreview}
              title="Close preview drawer"
              style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}
            >
              <X size={14} /> Close Preview
            </button>
          )}
        </div>
      </header>

      <section className="questions-shell" style={{ display: 'flex', gap: '1.5rem', flexDirection: 'row', alignItems: 'flex-start' }}>
        {/* Left Side: Search, Filters, and List */}
        <div className="questions-left" style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>

          {/* Search Bar */}
          <div className="questions-search-wrap" style={{ position: 'relative' }}>
            <span style={{ position: 'absolute', left: '1rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--muted)', display: 'flex', alignItems: 'center' }}>
              <Search size={16} />
            </span>
            <input
              type="text"
              aria-label="Search questions"
              placeholder="Search questions by keyword, company, topic, difficulty..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onFocus={() => { if (suggestions.length > 0) setShowSuggestions(true); }}
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
                  handleSelectQuestion(Number(row.qnum));
                  setShowSuggestions(false);
                  setSuggestionIndex(-1);
                } else if (e.key === 'Escape') {
                  e.stopPropagation();
                  setShowSuggestions(false);
                  setSuggestionIndex(-1);
                }
              }}
              style={{ width: '100%', padding: '0.75rem 1rem 0.75rem 2.5rem', borderRadius: 'var(--radius)', border: '1px solid var(--line)', background: 'var(--paper)', color: 'var(--ink)' }}
            />
            {showSuggestions && suggestions.length > 0 && (
              <div className="questions-search-suggestions" style={{ position: 'absolute', top: '100%', left: 0, right: 0, background: 'var(--paper)', border: '1px solid var(--line)', borderRadius: 'var(--radius)', zIndex: 20, marginTop: '0.5rem', boxShadow: 'var(--shadow)' }}>
                {suggestions.map((row, i) => (
                  <button
                    key={i}
                    type="button"
                    className={`questions-suggestion-item ${i === suggestionIndex ? "is-active" : ""}`}
                    style={{
                      display: 'flex', alignItems: 'center', gap: '0.5rem', width: '100%', padding: '0.75rem 1rem',
                      background: i === suggestionIndex ? 'var(--sidebar-hover)' : 'transparent',
                      border: 'none', borderBottom: '1px solid var(--line)', textAlign: 'left', cursor: 'pointer'
                    }}
                    onClick={() => {
                      setSearch(row.problem_name || "");
                      handleSelectQuestion(Number(row.qnum));
                      setShowSuggestions(false);
                      setSuggestionIndex(-1);
                    }}
                  >
                    <Search size={14} style={{ color: 'var(--muted)', flexShrink: 0 }} />
                    <span style={{ fontWeight: 500, color: 'var(--ink)' }}>{row.problem_name}</span>
                    <span style={{ marginLeft: 'auto', fontSize: '0.75rem', color: 'var(--muted)' }}>#{row.qnum} · {row.difficulty}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Filter Builder Component */}
          <section aria-label="Question filters">
            <FilterBuilder
              companies={COMPANY_FILTER_OPTIONS}
              topics={hydratedTopics}
              initialFilters={initialStatusFilter ? [initialStatusFilter] : undefined}
              onChange={handleFilterChange}
            />
          </section>

          {/* Questions Scrollable List */}
          <section ref={scrollerRef} aria-label="Questions list" style={{ flex: 1, overflowY: 'auto', maxHeight: '640px', paddingRight: '0.5rem' }}>
            <div className="q-browse-list" style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {rows.length === 0 && !isLoading && !isInitialLoad && !errorMsg ? (
                <div className="empty-state" style={{ padding: '2.5rem', textAlign: 'center', background: 'var(--paper)', borderRadius: 'var(--radius)', border: '1px solid var(--line)' }}>
                  <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '0.75rem' }}>
                    <ClipboardList size={36} className="text-muted" />
                  </div>
                  <p style={{ fontWeight: 600, color: 'var(--ink)', marginBottom: '0.25rem' }}>No matching questions found</p>
                  <p className="text-muted" style={{ fontSize: '0.9rem' }}>Try clearing or relaxing your search query or filters.</p>
                </div>
              ) : null}

              {rows.map((row) => {
                const isSelected = selectedQnum === Number(row.qnum);
                const diffColor = getDifficultyColor(row.difficulty);
                const isItemRevisit = revisitSet.has(Number(row.qnum));

                return (
                  <div
                    key={row.qnum}
                    className={`q-browse-item ${isSelected ? "is-selected" : ""}`}
                    tabIndex={0}
                    role="button"
                    aria-pressed={isSelected}
                    style={{
                      display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.9rem 1.1rem',
                      background: isSelected ? 'var(--sidebar-active)' : 'var(--paper)',
                      borderRadius: 'var(--radius)', border: isSelected ? '1px solid var(--teal)' : '1px solid var(--line)',
                      cursor: 'pointer', transition: 'all 150ms ease'
                    }}
                    onClick={() => handleSelectQuestion(Number(row.qnum))}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        handleSelectQuestion(Number(row.qnum));
                      }
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', minWidth: 0 }}>
                      <span style={{ color: 'var(--muted)', fontSize: '0.85rem', fontWeight: 600, minWidth: '40px' }}>#{row.qnum}</span>
                      <span style={{ fontWeight: 600, color: 'var(--ink)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {row.problem_name}
                      </span>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexShrink: 0 }}>
                      {row.solved === 1 && (
                        <span className="pill pill-solved" style={{ background: 'var(--green)', color: 'white', padding: '0.2rem 0.5rem', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }}>
                          <CheckCircle2 size={12} /> Solved
                        </span>
                      )}
                      {isItemRevisit && (
                        <span
                          className="pill"
                          title="In revisit queue"
                          style={{
                            background: "rgba(245, 158, 11, 0.15)",
                            color: "var(--amber)",
                            border: "1px solid rgba(245, 158, 11, 0.3)",
                            padding: "0.2rem 0.5rem",
                            borderRadius: "4px",
                            fontSize: "0.75rem",
                            fontWeight: 600,
                            display: "inline-flex",
                            alignItems: "center",
                            gap: "0.25rem",
                          }}
                        >
                          <RotateCcw size={11} /> Revisit
                        </span>
                      )}
                      <span className="pill" style={{
                        background: diffColor,
                        color: ['easy', 'medium', 'hard'].includes(String(row.difficulty || '').toLowerCase()) ? 'white' : 'inherit',
                        padding: '0.2rem 0.55rem', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600, textTransform: 'capitalize'
                      }}>
                        {row.difficulty}
                      </span>
                      <span className="pill" style={{ background: 'var(--sidebar-hover)', padding: '0.2rem 0.5rem', borderRadius: '4px', fontSize: '0.75rem', color: 'var(--muted)' }} title="Estimated success rate">
                        {estimateSuccessRate(row)}%
                      </span>
                    </div>
                  </div>
                );
              })}

              {isLoading && (
                <div style={{ padding: '1rem', display: 'flex', justifyContent: 'center' }}>
                  <Spinner text="Loading questions..." />
                </div>
              )}
              {errorMsg && (
                <div style={{ padding: '1rem', textAlign: 'center', color: 'var(--red)', background: 'rgba(239, 68, 68, 0.08)', borderRadius: 'var(--radius)' }}>
                  {errorMsg}
                </div>
              )}
              {!hasMore && rows.length > 0 && (
                <div style={{ padding: '1.25rem', textAlign: 'center', color: 'var(--muted)', fontSize: '0.9rem' }}>
                  You have reached the end of the question bank ({total} total questions).
                </div>
              )}
            </div>
          </section>
        </div>

        {/* Right Side / Question Preview Drawer */}
        <aside
          className="questions-right"
          aria-label="Selected question details"
          style={{
            width: '340px',
            flexShrink: 0,
            display: 'flex',
            flexDirection: 'column',
            gap: '1.25rem'
          }}
        >
          {selectedQuestion ? (
            <>
              {/* Question Details Card */}
              <article className="card-flat" style={{ padding: '1.5rem', background: 'var(--paper)', border: '1px solid var(--line)', borderRadius: 'var(--radius-lg)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.75rem', gap: '0.5rem' }}>
                  <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
                    <span className="counter-badge" style={{ fontSize: '0.8rem' }}>#{selectedQuestion.qnum}</span>
                    <span
                      className="pill"
                      style={{
                        background: getDifficultyColor(selectedQuestion.difficulty),
                        color: 'white',
                        padding: '0.15rem 0.5rem',
                        borderRadius: '4px',
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        textTransform: 'capitalize'
                      }}
                    >
                      {selectedQuestion.difficulty}
                    </span>
                    {selectedQuestion.solved === 1 && (
                      <span style={{ color: 'var(--green)', fontSize: '0.75rem', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: '0.2rem' }}>
                        <CheckCircle2 size={13} /> Solved
                      </span>
                    )}
                    {isSelectedRevisit && (
                      <span
                        style={{
                          color: "var(--amber)",
                          fontSize: "0.75rem",
                          fontWeight: 600,
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "0.25rem",
                          background: "rgba(245, 158, 11, 0.12)",
                          padding: "0.15rem 0.5rem",
                          borderRadius: "4px",
                          border: "1px solid rgba(245, 158, 11, 0.25)",
                        }}
                      >
                        <RotateCcw size={12} /> Revisit
                      </span>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={handleClosePreview}
                    aria-label="Close question preview"
                    title="Close preview (Escape)"
                    style={{ background: 'transparent', border: 'none', color: 'var(--muted)', cursor: 'pointer', padding: '0.2rem', display: 'flex', alignItems: 'center', borderRadius: '4px' }}
                  >
                    <X size={18} />
                  </button>
                </div>

                <h2 style={{ fontSize: '1.15rem', fontWeight: 700, marginBottom: '0.75rem', color: 'var(--ink)', lineHeight: 1.3 }}>
                  {selectedQuestion.problem_name}
                </h2>

                <div style={{ marginBottom: '1rem', fontSize: '0.88rem', color: 'var(--muted)', lineHeight: 1.5, maxHeight: '180px', overflowY: 'auto' }}>
                  {selectedQuestion.statement_text ? (
                    <p>{selectedQuestion.statement_text.length > 220 ? selectedQuestion.statement_text.substring(0, 220) + "..." : selectedQuestion.statement_text}</p>
                  ) : (
                    <p>Open this question to view the full prompt, examples, and test cases.</p>
                  )}
                </div>

                {/* Tags Section */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem', borderTop: '1px solid var(--line)', paddingTop: '0.85rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.82rem' }}>
                    <Building2 size={14} className="text-teal" style={{ flexShrink: 0 }} />
                    <span style={{ fontWeight: 600, color: 'var(--ink)' }}>Companies:</span>
                    <span style={{ color: 'var(--muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {(selectedQuestion.companies || selectedQuestion.company_tags || [selectedQuestion.company]).filter(Boolean).join(", ") || "General Practice"}
                    </span>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.82rem' }}>
                    <Tag size={14} className="text-teal" style={{ flexShrink: 0 }} />
                    <span style={{ fontWeight: 600, color: 'var(--ink)' }}>Topics:</span>
                    <span style={{ color: 'var(--muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {(selectedQuestion.topic_tags || []).join(", ") || "Data Structures & Algorithms"}
                    </span>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.82rem' }}>
                    <Clock size={14} className="text-teal" style={{ flexShrink: 0 }} />
                    <span style={{ fontWeight: 600, color: 'var(--ink)' }}>Success Rate:</span>
                    <span style={{ color: 'var(--muted)', fontWeight: 600 }}>
                      {estimateSuccessRate(selectedQuestion)}%
                    </span>
                  </div>

                  {/* Containing Custom Folders */}
                  {containingFolders.length > 0 && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.82rem', flexWrap: 'wrap' }}>
                      <Folder size={14} className="text-teal" style={{ flexShrink: 0 }} />
                      <span style={{ fontWeight: 600, color: 'var(--ink)' }}>Folders:</span>
                      {containingFolders.map((f) => (
                        <span
                          key={f.name}
                          style={{
                            fontSize: "0.75rem",
                            padding: "0.1rem 0.45rem",
                            borderRadius: "4px",
                            background: "rgba(20, 184, 166, 0.12)",
                            color: "var(--teal)",
                            border: "1px solid rgba(20, 184, 166, 0.25)",
                          }}
                        >
                          {f.name}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </article>

              {/* Actions Card */}
              <article className="card-flat" style={{ padding: '1.25rem', background: 'var(--paper)', border: '1px solid var(--line)', borderRadius: 'var(--radius-lg)' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
                  <Link
                    href={`/solve?qnum=${encodeURIComponent(selectedQuestion.qnum)}`}
                    className="btn btn-primary"
                    aria-label={`Practice question ${selectedQuestion.problem_name}`}
                    style={{
                      display: 'inline-flex',
                      justifyContent: 'center',
                      alignItems: 'center',
                      gap: '0.4rem',
                      fontWeight: 600,
                      padding: '0.75rem 1rem'
                    }}
                  >
                    <Play size={16} /> Practice
                  </Link>

                  <button
                    className={`btn ${isSelectedRevisit ? "btn-feedback-selected" : ""}`}
                    type="button"
                    disabled={isUpdatingRevisit}
                    onClick={toggleRevisit}
                    style={{
                      display: 'inline-flex',
                      justifyContent: 'center',
                      alignItems: 'center',
                      gap: '0.4rem',
                      fontSize: '0.9rem',
                      background: isSelectedRevisit ? 'rgba(245, 158, 11, 0.15)' : undefined,
                      color: isSelectedRevisit ? 'var(--amber)' : undefined,
                      borderColor: isSelectedRevisit ? 'var(--amber)' : undefined,
                    }}
                    title={isSelectedRevisit ? "Remove from revisit queue" : "Add to revisit queue"}
                  >
                    <RotateCcw size={15} />
                    {isSelectedRevisit ? "Remove from Revisit Queue" : "Add to Revisit Queue"}
                  </button>

                  <button
                    className="btn"
                    type="button"
                    onClick={() => setIsFolderModalOpen(true)}
                    style={{ display: 'inline-flex', justifyContent: 'center', alignItems: 'center', gap: '0.4rem', fontSize: '0.9rem' }}
                    title="Save question to custom folder"
                  >
                    <FolderPlus size={15} /> Save to Custom Folder
                  </button>
                </div>
              </article>
            </>
          ) : (
            <article className="card-flat" style={{ padding: '2rem 1.5rem', background: 'var(--paper)', border: '1px solid var(--line)', borderRadius: 'var(--radius-lg)', textAlign: 'center' }}>
              <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '0.75rem' }}>
                <ClipboardList size={36} className="text-muted" />
              </div>
              <h2 style={{ fontSize: '1.05rem', fontWeight: 600, marginBottom: '0.5rem', color: 'var(--ink)' }}>Question Preview</h2>
              <p className="text-muted" style={{ fontSize: '0.88rem', lineHeight: 1.5 }}>
                Click any question from the list to preview its problem statement, tags, success rate, and start practicing.
              </p>
            </article>
          )}
        </aside>
      </section>

      {/* Interactive Custom Folder Picker Modal */}
      {selectedQuestion && (
        <CustomFolderModal
          isOpen={isFolderModalOpen}
          onClose={() => setIsFolderModalOpen(false)}
          qnum={Number(selectedQuestion.qnum)}
          questionTitle={selectedQuestion.problem_name || `Question #${selectedQuestion.qnum}`}
          folders={folders}
          onAddToFolder={handleAddToFolder}
          onCreateFolderAndAdd={handleCreateFolderAndAdd}
        />
      )}
    </main>
  );
}

export default function QuestionsPage() {
  return (
    <Suspense
      fallback={
        <main className="main-content questions-main-content">
          <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "60vh" }}>
            <Spinner text="Loading questions..." />
          </div>
        </main>
      }
    >
      <QuestionsContent />
    </Suspense>
  );
}
