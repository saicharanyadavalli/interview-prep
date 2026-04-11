/**
 * filterBuilder.js - Chip-based filter UI for the All Questions v2 page.
 */

(function () {
  const DEFAULT_TOPIC_OPTIONS = [
    "arrays",
    "strings",
    "tree",
    "graph",
    "dynamic programming",
    "greedy",
    "stack",
    "queue",
    "heap",
    "binary search",
    "hash",
    "linked list",
  ];

  const DIFFICULTY_OPTIONS = ["easy", "medium", "hard"];
  const STATUS_OPTIONS = ["unsolved", "solved"];

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function normalizeText(value) {
    return String(value || "").trim().toLowerCase();
  }

  function uniqueNormalized(values) {
    return Array.from(
      new Set(
        (Array.isArray(values) ? values : [values])
          .map((item) => normalizeText(item))
          .filter(Boolean)
      )
    );
  }

  class FilterBuilder {
    constructor(rootEl, options = {}) {
      this.rootEl = rootEl;
      this.options = options;
      this.storageKey = options.storageKey || "questionsFilterBuilderStateV2";
      this.persist = options.persist !== false;
      this.maxVisibleTopics = Number(options.maxVisibleTopics || 10);
      this.onChange = typeof options.onChange === "function" ? options.onChange : function () {};

      this.availableTopics = uniqueNormalized(options.topics && options.topics.length ? options.topics : DEFAULT_TOPIC_OPTIONS);

      this.state = {
        version: 4,
        matchType: "all",
        difficulty: [],
        status: ["unsolved"],
        topic: [],
      };

      if (this.persist) {
        this._loadFromStorage();
      }

      this._sanitizeState();
      this.renderFilters();
      this._emitChange();
    }

    _loadFromStorage() {
      try {
        const raw = localStorage.getItem(this.storageKey);
        if (!raw) return;
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== "object") return;

        this.state = {
          version: 4,
          matchType: "all",
          difficulty: uniqueNormalized(parsed.difficulty || []),
          status: uniqueNormalized(parsed.status || []),
          topic: uniqueNormalized(parsed.topic || []),
        };
      } catch (_) {
        // Ignore malformed localStorage payload.
      }
    }

    _saveToStorage() {
      if (!this.persist) return;
      try {
        localStorage.setItem(
          this.storageKey,
          JSON.stringify({
            version: 4,
            difficulty: this.state.difficulty,
            status: this.state.status,
            topic: this.state.topic,
          })
        );
      } catch (_) {
        // Ignore localStorage quota errors.
      }
    }

    _sanitizeState() {
      this.state.difficulty = this.state.difficulty.filter((token) => DIFFICULTY_OPTIONS.includes(token));
      this.state.status = this.state.status.filter((token) => STATUS_OPTIONS.includes(token));
      this.state.topic = this.state.topic.filter((token) => this.availableTopics.includes(token));
    }

    _emitChange() {
      this._saveToStorage();
      this.onChange(this.getState(), this.getQueryObject());
    }

    getState() {
      return clone(this.state);
    }

    getActiveFilterCount() {
      return this.state.difficulty.length + this.state.status.length + this.state.topic.length;
    }

    setTopics(topics) {
      const discovered = uniqueNormalized(topics);
      if (!discovered.length) return;

      const before = this.availableTopics.join("|");
      const merged = Array.from(new Set([...(this.options.topics || []), ...this.availableTopics, ...discovered]));
      this.availableTopics = uniqueNormalized(merged);
      const after = this.availableTopics.join("|");

      if (before === after) {
        return;
      }

      this._sanitizeState();
      this.renderFilters();
    }

    setCompanies() {
      // Companies are handled via search on this page version.
    }

    getQueryObject() {
      return {
        match: "all",
        status: this.state.status.slice(),
        difficulty: this.state.difficulty.slice(),
        company: [],
        topic: this.state.topic.slice(),
      };
    }

    _toLabel(value) {
      const text = String(value || "").trim();
      if (!text) return "";
      if (text.toLowerCase() === "unsolved") return "New";
      return text
        .split(" ")
        .filter(Boolean)
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(" ");
    }

    _renderGroup(label, field, options) {
      const selectedSet = new Set(this.state[field] || []);
      const chips = options
        .map((value) => {
          const isActive = selectedSet.has(value);
          return `
            <button
              type="button"
              class="qv2-chip ${isActive ? "is-active" : ""}"
              data-field="${field}"
              data-value="${value}"
              aria-pressed="${isActive ? "true" : "false"}"
            >
              ${this._toLabel(value)}
            </button>
          `;
        })
        .join("");

      return `
        <div class="qv2-filter-group" data-field="${field}">
          <p class="qv2-filter-label">${label}</p>
          <div class="qv2-chip-row">
            ${chips}
          </div>
        </div>
      `;
    }

    renderFilters() {
      if (!this.rootEl) return;

      this._sanitizeState();

      const topicsToShow = this.availableTopics.slice(0, this.maxVisibleTopics);

      this.rootEl.innerHTML = `
        <div class="qv2-filter-card">
          ${this._renderGroup("Difficulty", "difficulty", DIFFICULTY_OPTIONS)}
          ${this._renderGroup("Topic", "topic", topicsToShow)}
          ${this._renderGroup("Status", "status", STATUS_OPTIONS)}

          <div class="qv2-filter-actions">
            <button id="filterResetBtn" class="btn btn-sm" type="button">Clear Filters</button>
          </div>
        </div>
      `;

      this._bindEvents();
    }

    _toggleToken(field, value) {
      if (!this.state[field]) return;

      const current = new Set(this.state[field]);
      if (current.has(value)) {
        current.delete(value);
      } else {
        if (field === "status") {
          current.clear();
        }
        current.add(value);
      }

      this.state[field] = Array.from(current);
      this._sanitizeState();
      this.renderFilters();
      this._emitChange();
    }

    _bindEvents() {
      this.rootEl.querySelectorAll(".qv2-chip").forEach((chip) => {
        chip.addEventListener("click", () => {
          const field = normalizeText(chip.getAttribute("data-field"));
          const value = normalizeText(chip.getAttribute("data-value"));
          this._toggleToken(field, value);
        });
      });

      const resetBtn = this.rootEl.querySelector("#filterResetBtn");
      if (resetBtn) {
        resetBtn.addEventListener("click", () => {
          this.resetFilters();
        });
      }
    }

    resetFilters() {
      this.state = {
        version: 4,
        matchType: "all",
        difficulty: [],
        status: ["unsolved"],
        topic: [],
      };
      this._sanitizeState();
      this.renderFilters();
      this._emitChange();
    }

    // Compatibility helpers for previous builder API.
    addFilter() {
      this.resetFilters();
    }

    removeFilter() {
      this.resetFilters();
    }

    updateFilter() {
      this._emitChange();
    }
  }

  window.FilterBuilder = FilterBuilder;
})();
