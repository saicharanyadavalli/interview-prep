"use client";

import React, { useEffect, useState, useCallback } from "react";
import { Drawer } from "@/components/ui/Drawer";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { API } from "@/lib/api";
import Link from "next/link";
import { ExternalLink, CheckCircle, RotateCcw, FolderPlus, Check } from "lucide-react";
import { CustomFolderModal, CustomFolderItem } from "./CustomFolderModal";

const CUSTOM_FOLDERS_STORAGE_KEY = "questionsCustomFolders_v2";
const DEFAULT_FOLDERS: CustomFolderItem[] = [
  { name: "Favorites", qnums: [], count: 0 },
  { name: "Striver SDE Sheet", qnums: [], count: 0 },
  { name: "Must Revise", qnums: [], count: 0 },
];

export interface QuestionDrawerProps {
  qnum: number | null;
  onClose: () => void;
}

export const QuestionDrawer: React.FC<QuestionDrawerProps> = ({ qnum, onClose }) => {
  const [data, setData] = useState<any>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isRevisit, setIsRevisit] = useState(false);
  const [isUpdatingRevisit, setIsUpdatingRevisit] = useState(false);
  const [isFolderModalOpen, setIsFolderModalOpen] = useState(false);
  const [folders, setFolders] = useState<CustomFolderItem[]>(DEFAULT_FOLDERS);
  const [revisitFeedback, setRevisitFeedback] = useState<string | null>(null);

  // Load custom folders from localStorage and API
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
  }, []);

  // Fetch question details and revisit status
  useEffect(() => {
    if (!qnum) {
      setData(null);
      setIsRevisit(false);
      setRevisitFeedback(null);
      return;
    }
    setIsLoading(true);
    setRevisitFeedback(null);

    Promise.all([
      API.getQuestionByQnum(String(qnum)).catch(() => null),
      API.getProgressStatus(String(qnum)).catch(() => null),
    ])
      .then(([qData, statusData]) => {
        setData(qData);
        if (statusData && typeof statusData.revisit === "boolean") {
          setIsRevisit(statusData.revisit);
        }
      })
      .finally(() => setIsLoading(false));
  }, [qnum]);

  const toggleRevisit = async () => {
    if (!qnum || isUpdatingRevisit) return;
    const nextState = !isRevisit;
    setIsUpdatingRevisit(true);
    setIsRevisit(nextState);
    setRevisitFeedback(nextState ? "Added to revisit queue" : "Removed from revisit queue");

    try {
      await API.updateProgress(qnum, { revisit: nextState });
      if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("ipp_revisit_updated", {
            detail: { qnum, revisit: nextState },
          })
        );
      }
      setTimeout(() => setRevisitFeedback(null), 2500);
    } catch (err: any) {
      // Rollback on error
      setIsRevisit(!nextState);
      setRevisitFeedback(`Failed to update revisit: ${err.message}`);
    } finally {
      setIsUpdatingRevisit(false);
    }
  };

  const handleAddToFolder = useCallback(
    async (folderName: string) => {
      if (!qnum) return { success: false, message: "No question selected." };

      const existingFolder = folders.find((f) => f.name.toLowerCase() === folderName.toLowerCase());
      if (existingFolder && existingFolder.qnums.includes(qnum)) {
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

      try {
        await API.addQuestionToFolder(folderName, qnum);
      } catch (_) {}

      return { success: true, alreadyPresent: false };
    },
    [qnum, folders]
  );

  const handleCreateFolderAndAdd = useCallback(
    async (folderName: string) => {
      if (!qnum) return { success: false, message: "No question selected." };

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

      try {
        await API.createCustomFolder(trimmed, [qnum]);
      } catch (_) {}

      return { success: true, alreadyPresent: false };
    },
    [qnum, folders, handleAddToFolder]
  );

  const titleText = data?.problem_name || data?.title || (qnum ? `Question #${qnum}` : "Question Details");

  return (
    <>
      <Drawer isOpen={Boolean(qnum)} onClose={onClose} title={titleText}>
        {isLoading ? (
          <div className="space-y-4">
            <Skeleton height="h-6" width="w-3/4" />
            <Skeleton height="h-24" width="w-full" />
            <Skeleton height="h-32" width="w-full" />
          </div>
        ) : data ? (
          <div className="space-y-6 text-ink">
            {/* Header Tags */}
            <div className="flex items-center gap-3 flex-wrap">
              <Badge variant={data.difficulty?.toLowerCase() === "easy" ? "easy" : data.difficulty?.toLowerCase() === "hard" ? "hard" : "medium"}>
                {data.difficulty || "Medium"}
              </Badge>
              {(data.company || data.primary_company) && (
                <Badge variant="neutral">{data.company || data.primary_company}</Badge>
              )}
              {isRevisit && (
                <Badge variant="revisit">
                  <RotateCcw size={11} className="inline mr-1" /> Revisit
                </Badge>
              )}
            </div>

            {/* Revisit inline feedback */}
            {revisitFeedback && (
              <div className="text-xs px-3 py-1.5 rounded-lg bg-teal/10 text-teal border border-teal/20 flex items-center gap-1.5 animate-in fade-in">
                <Check size={12} />
                <span>{revisitFeedback}</span>
              </div>
            )}

            {/* Statement Preview */}
            <div className="prose max-w-none text-sm leading-relaxed bg-surface-soft p-4 rounded-xl border border-line text-ink">
              <h4 className="text-xs uppercase tracking-wider text-muted font-bold mb-2">Statement</h4>
              <p className="text-ink">{data.statement_text || data.statement || data.problem_description || "No detailed statement preview available."}</p>
            </div>

            {/* Action Buttons */}
            <div className="pt-2 flex flex-col gap-2.5">
              <Link href={`/solve?qnum=${encodeURIComponent(qnum || 0)}`} className="w-full">
                <Button size="md" className="w-full justify-center" rightIcon={<ExternalLink size={14} />}>
                  Open Full Practice Workspace
                </Button>
              </Link>

              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={toggleRevisit}
                  disabled={isUpdatingRevisit}
                  className={`btn flex-1 justify-center gap-2 text-sm ${
                    isRevisit ? "btn-feedback-selected" : ""
                  }`}
                  style={{
                    background: isRevisit ? "rgba(245, 158, 11, 0.15)" : "var(--surface-chip)",
                    borderColor: isRevisit ? "var(--amber)" : "var(--line)",
                    color: isRevisit ? "var(--amber)" : "var(--ink)",
                  }}
                  title={isRevisit ? "Remove from revisit queue" : "Add to revisit queue"}
                >
                  <RotateCcw size={14} />
                  {isRevisit ? "In Revisit Queue" : "Add to Revisit"}
                </button>

                <button
                  type="button"
                  onClick={() => setIsFolderModalOpen(true)}
                  className="btn flex-1 justify-center gap-2 text-sm"
                  style={{
                    background: "var(--surface-chip)",
                    borderColor: "var(--line)",
                    color: "var(--ink)",
                  }}
                  title="Save question to custom folder"
                >
                  <FolderPlus size={14} />
                  Folder
                </button>
              </div>
            </div>
          </div>
        ) : (
          <p className="text-muted">Question details unavailable.</p>
        )}
      </Drawer>

      {/* Custom Folder Modal */}
      {qnum && (
        <CustomFolderModal
          isOpen={isFolderModalOpen}
          onClose={() => setIsFolderModalOpen(false)}
          qnum={qnum}
          questionTitle={titleText}
          folders={folders}
          onAddToFolder={handleAddToFolder}
          onCreateFolderAndAdd={handleCreateFolderAndAdd}
        />
      )}
    </>
  );
};
