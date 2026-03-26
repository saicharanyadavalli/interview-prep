/**
 * filterBuilder.js - Reusable filter builder component.
 *
 * Supported fields:
 * - status
 * - difficulty
 * - company
 * - topic
 */

(function () {
  const DEFAULT_TOPIC_OPTIONS = [
    "arrays",
    "strings",
    "linked list",
    "stack",
    "queue",
    "hashing",
    "trees",
    "binary search tree",
    "heap",
    "graph",
    "dynamic programming",
    "greedy",
    "backtracking",
    "sliding window",
    "two pointers",
    "bit manipulation",
    "math",
    "sorting",
    "searching",
  ];

  const FIELD_DEFS = {
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
      values: DEFAULT_TOPIC_OPTIONS.slice(),
    },
  };

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function normalizeText(value) {
    return String(value || "").trim().toLowerCase();
  }

  class FilterBuilder {
    constructor(rootEl, options = {}) {
      this.rootEl = rootEl;
      this.options = options;
      this.storageKey = options.storageKey || "questionsFilterBuilderState";
      this.persist = options.persist !== false;
      this.onChange = typeof options.onChange === "function" ? options.onChange : function () {};

      if (Array.isArray(this.options.companies) && !this.options.companyLabels) {
        const labels = {};
        this.options.companies.forEach((item) => {
          const raw = String(item || "").trim();
          const normalized = normalizeText(raw);
          if (!normalized) return;
          if (!labels[normalized]) {
            labels[normalized] = raw;
          }
        });
        this.options.companies = Object.keys(labels);
        this.options.companyLabels = labels;
      }

      this.state = {
        version: 3,
        matchType: "all",
        filters: [],
      };

      if (this.persist) {
        this._loadFromStorage();
      }

      if (!Array.isArray(this.state.filters)) {
        this.state.filters = [];
      }

      this.renderFilters();
      this._emitChange();
    }

    _createDefaultFilter() {
      return { field: "status", operator: "is", value: "unsolved" };
    }

    _getTopicValues() {
      const fromOptions = Array.isArray(this.options.topics)
        ? this.options.topics.map(normalizeText).filter(Boolean)
        : [];

      const fallback = FIELD_DEFS.topic.values;
      const unique = new Set([...(fromOptions.length ? fromOptions : fallback)]);
      return Array.from(unique);
    }

    _getCompanyValues() {
      const fromOptions = Array.isArray(this.options.companies)
        ? this.options.companies.map(normalizeText).filter(Boolean)
        : [];

      const fallback = FIELD_DEFS.company.values;
      const unique = new Set([...(fromOptions.length ? fromOptions : fallback)]);
      return Array.from(unique);
    }

    _getValuesForField(field) {
      const key = normalizeText(field);
      if (key === "topic") {
        return this._getTopicValues();
      }
      if (key === "company") {
        return this._getCompanyValues();
      }
      return (FIELD_DEFS[key] && FIELD_DEFS[key].values) ? FIELD_DEFS[key].values.slice() : [];
    }

    _sanitizeState() {
      const validMatch = this.state.matchType === "any" ? "any" : "all";
      this.state.matchType = validMatch;

      const cleaned = [];
      (this.state.filters || []).forEach((item) => {
        const field = normalizeText(item && item.field);
        if (!FIELD_DEFS[field]) return;

        const operator = normalizeText(item.operator) === "is not" ? "is not" : "is";
        const values = this._getValuesForField(field);
        let value = normalizeText(item.value);
        if (!values.includes(value)) {
          return;
        }

        if (value) {
          cleaned.push({ field: field, operator: operator, value: value });
        }
      });

      this.state.filters = cleaned;
    }

    _loadFromStorage() {
      try {
        const raw = localStorage.getItem(this.storageKey);
        if (!raw) return;
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== "object") return;

        const legacyDefaultOnly =
          !parsed.version
          && Array.isArray(parsed.filters)
          && parsed.filters.length === 1
          && normalizeText(parsed.filters[0]?.field) === "status"
          && normalizeText(parsed.filters[0]?.operator) === "is"
          && normalizeText(parsed.filters[0]?.value) === "strong";

        this.state = {
          version: 3,
          matchType: parsed.matchType || "all",
          filters: legacyDefaultOnly ? [] : (Array.isArray(parsed.filters) ? parsed.filters : []),
        };
        this._sanitizeState();
      } catch (_) {
        // Ignore malformed localStorage payload.
      }
    }

    _saveToStorage() {
      if (!this.persist) return;
      try {
        localStorage.setItem(this.storageKey, JSON.stringify({
          version: 3,
          matchType: this.state.matchType,
          filters: this.state.filters,
        }));
      } catch (_) {
        // Ignore localStorage quota issues.
      }
    }

    _emitChange() {
      this._saveToStorage();
      this.onChange(this.getState(), this.getQueryObject());
    }

    getState() {
      return clone(this.state);
    }

    getActiveFilterCount() {
      return (this.state.filters || []).length;
    }

    setTopics(topics) {
      if (!Array.isArray(topics)) return;
      const normalized = Array.from(new Set(topics.map(normalizeText).filter(Boolean)));
      if (!normalized.length) return;
      this.options.topics = normalized;
      this._sanitizeState();
      this.renderFilters();
      this._emitChange();
    }

    setCompanies(companies) {
      if (!Array.isArray(companies)) return;
      const labels = {};
      companies.forEach((item) => {
        const raw = String(item || "").trim();
        const normalized = normalizeText(raw);
        if (!normalized) return;
        if (!labels[normalized]) {
          labels[normalized] = raw;
        }
      });

      const normalized = Object.keys(labels);
      if (!normalized.length) return;
      this.options.companies = normalized;
      this.options.companyLabels = labels;
      this._sanitizeState();
      this.renderFilters();
      this._emitChange();
    }

    getQueryObject() {
      const result = {
        match: this.state.matchType,
        status: [],
        difficulty: [],
        company: [],
        topic: [],
      };

      (this.state.filters || []).forEach((item) => {
        const field = normalizeText(item.field);
        if (!result[field]) return;
        const value = normalizeText(item.value);
        if (!value) return;
        const token = item.operator === "is not" ? `!${value}` : value;
        result[field].push(token);
      });

      return result;
    }

    renderFilters() {
      if (!this.rootEl) return;

      this._sanitizeState();

      const rows = (this.state.filters || [])
        .map((filter, index) => this._renderFilterRow(filter, index))
        .join("");

      const emptyState = !rows
        ? '<p class="filter-builder-empty text-muted">No filters applied. Showing all questions.</p>'
        : "";

      this.rootEl.innerHTML = `
        <div class="filter-builder-card">
          <div class="filter-builder-head">
            <span class="filter-head-label">Match</span>
            <select id="filterBuilderMatchType" class="filter-builder-match" aria-label="Filter match type">
              <option value="all" ${this.state.matchType === "all" ? "selected" : ""}>All</option>
              <option value="any" ${this.state.matchType === "any" ? "selected" : ""}>Any</option>
            </select>
            <span class="filter-head-label">of the following filters</span>
            <span id="filterCountBadge" class="counter-badge filter-count-pill">${this.getActiveFilterCount()}</span>
          </div>

          <div id="filterBuilderRows" class="filter-builder-rows">
            ${emptyState}
            ${rows}
          </div>

          <div class="filter-builder-actions">
            <button id="filterAddBtn" type="button" class="btn btn-sm">+ Add Filter</button>
            <button id="filterResetBtn" type="button" class="btn btn-sm">Reset</button>
          </div>
        </div>
      `;

      this._bindEvents();
    }

    _renderFilterRow(filter, index) {
      const fieldOptions = Object.keys(FIELD_DEFS)
        .map((key) => `<option value="${key}" ${filter.field === key ? "selected" : ""}>${FIELD_DEFS[key].label}</option>`)
        .join("");

      const valueOptions = this._getValuesForField(filter.field)
        .map((value) => `<option value="${value}" ${filter.value === value ? "selected" : ""}>${this._toLabelForField(filter.field, value)}</option>`)
        .join("");

      return `
        <div class="filter-builder-row" data-index="${index}">
          <select class="filter-field" aria-label="Filter field" title="Field">${fieldOptions}</select>
          <select class="filter-operator" aria-label="Filter operator">
            <option value="is" ${filter.operator === "is" ? "selected" : ""}>is</option>
            <option value="is not" ${filter.operator === "is not" ? "selected" : ""}>is not</option>
          </select>
          <select class="filter-value" aria-label="Filter value" title="Value">${valueOptions}</select>
          <button type="button" class="btn btn-sm filter-remove" aria-label="Remove filter" title="Remove filter">Remove</button>
        </div>
      `;
    }

    _toLabel(value) {
      const text = String(value || "").trim();
      if (!text) return "";
      if (text.toLowerCase() === "unsolved") return "Not Solved";
      return text
        .split(" ")
        .filter(Boolean)
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(" ");
    }

    _toLabelForField(field, value) {
      if (normalizeText(field) === "company") {
        const labels = this.options.companyLabels || {};
        const exact = labels[normalizeText(value)];
        if (exact) return exact;
      }
      return this._toLabel(value);
    }

    _bindEvents() {
      const matchSelect = this.rootEl.querySelector("#filterBuilderMatchType");
      const addBtn = this.rootEl.querySelector("#filterAddBtn");
      const resetBtn = this.rootEl.querySelector("#filterResetBtn");

      if (matchSelect) {
        matchSelect.addEventListener("change", (event) => {
          this.state.matchType = event.target.value === "any" ? "any" : "all";
          this._emitChange();
        });
      }

      if (addBtn) {
        addBtn.addEventListener("click", () => {
          this.addFilter();
        });
      }

      if (resetBtn) {
        resetBtn.addEventListener("click", () => {
          this.resetFilters();
        });
      }

      this.rootEl.querySelectorAll(".filter-builder-row").forEach((rowEl) => {
        const index = Number(rowEl.getAttribute("data-index"));
        const fieldSel = rowEl.querySelector(".filter-field");
        const opSel = rowEl.querySelector(".filter-operator");
        const valueSel = rowEl.querySelector(".filter-value");
        const removeBtn = rowEl.querySelector(".filter-remove");

        if (fieldSel) {
          fieldSel.addEventListener("change", (event) => {
            this.updateFilter(index, "field", event.target.value);
          });
        }
        if (opSel) {
          opSel.addEventListener("change", (event) => {
            this.updateFilter(index, "operator", event.target.value);
          });
        }
        if (valueSel) {
          valueSel.addEventListener("change", (event) => {
            this.updateFilter(index, "value", event.target.value);
          });
        }
        if (removeBtn) {
          removeBtn.addEventListener("click", () => {
            this.removeFilter(index);
          });
        }
      });
    }

    addFilter() {
      this.state.filters.push(this._createDefaultFilter());
      this.renderFilters();
      this._emitChange();
    }

    removeFilter(index) {
      if (!Array.isArray(this.state.filters)) return;
      this.state.filters = this.state.filters.filter((_, i) => i !== index);
      this.renderFilters();
      this._emitChange();
    }

    updateFilter(index, key, value) {
      const current = this.state.filters[index];
      if (!current) return;

      if (key === "field") {
        const field = normalizeText(value);
        if (!FIELD_DEFS[field]) return;
        current.field = field;
        const values = this._getValuesForField(field);
        current.value = values[0] || "";
      } else if (key === "operator") {
        current.operator = normalizeText(value) === "is not" ? "is not" : "is";
      } else if (key === "value") {
        current.value = normalizeText(value);
      }

      this._sanitizeState();
      this.renderFilters();
      this._emitChange();
    }

    resetFilters() {
      this.state = {
        matchType: "all",
        filters: [],
      };
      this.renderFilters();
      this._emitChange();
    }
  }

  window.FilterBuilder = FilterBuilder;
})();
