"use client";

import React, { useEffect } from "react";
import { useQuestionCatalog } from "@/hooks/useQuestionCatalog";
import { QuestionTable } from "@/components/questions/QuestionTable";
import { QuestionDrawer } from "@/components/questions/QuestionDrawer";
import { FilterBuilder } from "@/components/FilterBuilder";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { Search } from "lucide-react";

export default function QuestionsPage() {
  const {
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
  } = useQuestionCatalog();

  useEffect(() => {
    fetchCatalog(true);
  }, []);

  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setSearch(val);
    fetchCatalog(true, val, filterQuery);
  };

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-zinc-800 pb-5">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight text-white">Question Catalog</h1>
          <p className="text-sm text-zinc-400 mt-1">
            Browse and search through {total ? total : "1080+"} DSA interview questions.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <FilterBuilder
            onChange={(_, queryObj) => {
              setFilterQuery(queryObj);
              fetchCatalog(true, search, queryObj);
            }}
          />
        </div>
      </div>

      {/* Search Input */}
      <div className="max-w-md">
        <Input
          placeholder="Search by title, topic, or company..."
          value={search}
          onChange={handleSearchChange}
          leftIcon={<Search size={16} />}
        />
      </div>

      {/* Error Banner */}
      {errorMsg && (
        <div className="p-4 bg-rose-500/10 border border-rose-500/20 text-rose-400 text-sm rounded-lg">
          {errorMsg}
        </div>
      )}

      {/* Table */}
      {isLoading && rows.length === 0 ? (
        <div className="space-y-3">
          <Skeleton height="h-12" width="w-full" />
          <Skeleton height="h-12" width="w-full" />
          <Skeleton height="h-12" width="w-full" />
        </div>
      ) : (
        <QuestionTable
          questions={rows}
          onSelectQuestion={(qnum) => setSelectedQnum(qnum)}
          isLoading={isLoading}
        />
      )}

      {/* Pagination / Load More */}
      {hasMore && (
        <div className="flex justify-center pt-4">
          <Button
            variant="outline"
            onClick={() => fetchCatalog(false)}
            isLoading={isLoading}
          >
            Load More Questions
          </Button>
        </div>
      )}

      {/* Detail Side Sheet */}
      <QuestionDrawer
        qnum={selectedQnum}
        onClose={() => setSelectedQnum(null)}
      />
    </div>
  );
}
