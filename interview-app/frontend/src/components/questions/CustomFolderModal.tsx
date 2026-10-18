"use client";

import React, { useState, useEffect, useRef } from "react";
import { FolderPlus, FolderCheck, Check, Plus, X, Folder, AlertCircle } from "lucide-react";

export interface CustomFolderItem {
  id?: string;
  name: string;
  qnums: number[];
  count: number;
}

export interface CustomFolderModalProps {
  isOpen: boolean;
  onClose: () => void;
  qnum: number;
  questionTitle: string;
  folders: CustomFolderItem[];
  onAddToFolder: (folderName: string) => Promise<{ success: boolean; alreadyPresent?: boolean; message?: string }>;
  onCreateFolderAndAdd: (folderName: string) => Promise<{ success: boolean; alreadyPresent?: boolean; message?: string }>;
}

export const CustomFolderModal: React.FC<CustomFolderModalProps> = ({
  isOpen,
  onClose,
  qnum,
  questionTitle,
  folders,
  onAddToFolder,
  onCreateFolderAndAdd,
}) => {
  const [newFolderName, setNewFolderName] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [actionFeedback, setActionFeedback] = useState<{ message: string; type: "success" | "info" | "error" } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen) {
        onClose();
      }
    };
    if (isOpen) {
      window.addEventListener("keydown", handleKeyDown);
      setActionFeedback(null);
      setNewFolderName("");
      setTimeout(() => {
        inputRef.current?.focus();
      }, 50);
    }
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleAddExisting = async (folderName: string) => {
    setIsSubmitting(true);
    setActionFeedback(null);
    try {
      const res = await onAddToFolder(folderName);
      if (res.alreadyPresent) {
        setActionFeedback({
          message: `Question #${qnum} is already in "${folderName}".`,
          type: "info",
        });
      } else {
        setActionFeedback({
          message: `Added Question #${qnum} to "${folderName}".`,
          type: "success",
        });
      }
    } catch (err: any) {
      setActionFeedback({
        message: `Failed to add to "${folderName}": ${err.message}`,
        type: "error",
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCreateAndAdd = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const trimmed = newFolderName.trim();
    if (!trimmed) {
      setActionFeedback({ message: "Please enter a folder name.", type: "error" });
      return;
    }
    setIsSubmitting(true);
    setActionFeedback(null);
    try {
      const res = await onCreateFolderAndAdd(trimmed);
      setNewFolderName("");
      if (res.alreadyPresent) {
        setActionFeedback({
          message: `Question #${qnum} is already in "${trimmed}".`,
          type: "info",
        });
      } else {
        setActionFeedback({
          message: `Created folder "${trimmed}" and added Question #${qnum}!`,
          type: "success",
        });
      }
    } catch (err: any) {
      setActionFeedback({
        message: `Failed to create folder: ${err.message}`,
        type: "error",
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-in fade-in duration-200"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="custom-folder-modal-title"
    >
      <div
        className="relative w-full max-w-md bg-paper border border-line rounded-2xl shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200 text-ink"
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--paper)",
          color: "var(--ink)",
          border: "1px solid var(--line)",
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-6 py-4 border-b border-line"
          style={{ borderColor: "var(--line)" }}
        >
          <div className="flex items-center gap-2.5">
            <div
              className="p-2 rounded-lg bg-teal/10 text-teal"
              style={{ background: "rgba(20, 184, 166, 0.15)", color: "var(--teal)" }}
            >
              <FolderPlus size={20} />
            </div>
            <div>
              <h3 id="custom-folder-modal-title" className="font-bold text-base leading-tight">
                Save to Custom Folder
              </h3>
              <p className="text-xs text-muted" style={{ color: "var(--muted)" }}>
                Question #{qnum} · {questionTitle.length > 30 ? questionTitle.substring(0, 30) + "..." : questionTitle}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close modal"
            className="p-1.5 rounded-lg text-muted hover:text-ink hover:bg-sidebar-hover transition-colors"
            style={{ color: "var(--muted)" }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Feedback message banner */}
        {actionFeedback && (
          <div
            className={`px-5 py-3 text-xs font-semibold flex items-center gap-2 ${
              actionFeedback.type === "success"
                ? "bg-emerald-500/15 text-emerald-400 border-b border-emerald-500/20"
                : actionFeedback.type === "info"
                ? "bg-amber-500/15 text-amber-300 border-b border-amber-500/20"
                : "bg-red-500/15 text-red-400 border-b border-red-500/20"
            }`}
          >
            {actionFeedback.type === "success" ? (
              <Check size={14} className="flex-shrink-0" />
            ) : (
              <AlertCircle size={14} className="flex-shrink-0" />
            )}
            <span>{actionFeedback.message}</span>
          </div>
        )}

        {/* Body: Folder List */}
        <div className="p-5 space-y-4 max-h-80 overflow-y-auto">
          <div>
            <span
              className="text-xs font-bold uppercase tracking-wider text-muted block mb-2"
              style={{ color: "var(--muted, #a1a1aa)" }}
            >
              Select Folder
            </span>

            {folders.length === 0 ? (
              <div
                className="p-4 rounded-xl text-center text-xs text-muted border border-dashed border-line"
                style={{ borderColor: "var(--line)", color: "var(--muted)" }}
              >
                No folders created yet. Create your first folder below!
              </div>
            ) : (
              <div className="space-y-2">
                {folders.map((folder) => {
                  const isAlreadyIn = folder.qnums.includes(qnum);
                  return (
                    <div
                      key={folder.name}
                      className="flex items-center justify-between p-3 rounded-xl transition-colors border"
                      style={{
                        background: isAlreadyIn ? "var(--sidebar-active)" : "var(--surface-soft)",
                        borderColor: isAlreadyIn ? "var(--teal)" : "var(--line)",
                      }}
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        {isAlreadyIn ? (
                          <FolderCheck size={18} className="text-teal flex-shrink-0" style={{ color: "var(--teal)" }} />
                        ) : (
                          <Folder size={18} className="text-muted flex-shrink-0" style={{ color: "var(--muted)" }} />
                        )}
                        <div className="min-w-0">
                          <p className="font-semibold text-sm truncate" style={{ color: "var(--ink)" }}>
                            {folder.name}
                          </p>
                          <p className="text-xs text-muted" style={{ color: "var(--muted)" }}>
                            {folder.count} {folder.count === 1 ? "question" : "questions"}
                          </p>
                        </div>
                      </div>

                      {isAlreadyIn ? (
                        <span
                          className="px-2.5 py-1 text-xs font-semibold rounded-md flex items-center gap-1.5"
                          style={{
                            background: "rgba(20, 184, 166, 0.2)",
                            color: "var(--teal)",
                          }}
                        >
                          <Check size={12} /> Added
                        </span>
                      ) : (
                        <button
                          type="button"
                          disabled={isSubmitting}
                          onClick={() => handleAddExisting(folder.name)}
                          className="btn btn-sm"
                          style={{
                            fontSize: "0.8rem",
                            padding: "0.3rem 0.75rem",
                            cursor: isSubmitting ? "not-allowed" : "pointer",
                          }}
                        >
                          <Plus size={13} /> Add
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Create New Folder */}
          <form onSubmit={handleCreateAndAdd} className="pt-3 border-t border-line" style={{ borderColor: "var(--line)" }}>
            <span
              className="text-xs font-bold uppercase tracking-wider text-muted block mb-2"
              style={{ color: "var(--muted)" }}
            >
              Create New Folder
            </span>
            <div className="flex items-center gap-2">
              <input
                ref={inputRef}
                type="text"
                placeholder="e.g. Striver SDE Sheet, Revision..."
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                disabled={isSubmitting}
                className="form-control"
                style={{
                  flex: 1,
                  padding: "0.55rem 0.85rem",
                  fontSize: "0.88rem",
                  borderRadius: "var(--radius, 8px)",
                  border: "1px solid var(--line)",
                  background: "var(--surface-chip)",
                  color: "var(--ink)",
                }}
              />
              <button
                type="submit"
                disabled={isSubmitting || !newFolderName.trim()}
                className="btn btn-primary"
                style={{
                  padding: "0.55rem 0.95rem",
                  fontSize: "0.85rem",
                  whiteSpace: "nowrap",
                }}
              >
                <Plus size={14} /> Create & Add
              </button>
            </div>
          </form>
        </div>

        {/* Footer */}
        <div
          className="flex justify-end px-5 py-3 border-t border-line bg-surface-soft"
          style={{ borderColor: "var(--line)" }}
        >
          <button
            type="button"
            onClick={onClose}
            className="btn btn-sm"
            style={{ padding: "0.45rem 1.1rem" }}
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
};
