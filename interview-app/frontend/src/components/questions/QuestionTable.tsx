import React from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ExternalLink, CheckCircle, Clock } from "lucide-react";

export interface QuestionTableProps {
  questions: any[];
  onSelectQuestion: (qnum: number) => void;
  isLoading: boolean;
}

export const QuestionTable: React.FC<QuestionTableProps> = React.memo(
  ({ questions, onSelectQuestion, isLoading }) => {
    if (questions.length === 0 && !isLoading) {
      return (
        <div className="p-12 text-center border border-zinc-800 rounded-xl bg-zinc-900/40 my-4">
          <p className="text-zinc-400 font-medium text-sm">No questions found matching your filter criteria.</p>
        </div>
      );
    }

    return (
      <div className="w-full overflow-x-auto border border-zinc-800/80 rounded-xl bg-zinc-900/60 backdrop-blur-sm shadow-xl">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-zinc-800 bg-zinc-950/60 text-xs font-semibold text-zinc-400 uppercase tracking-wider">
              <th className="py-3.5 px-4 w-16">#</th>
              <th className="py-3.5 px-4">Title</th>
              <th className="py-3.5 px-4 w-28">Difficulty</th>
              <th className="py-3.5 px-4 w-24">Status</th>
              <th className="py-3.5 px-4 w-32 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/60 text-sm">
            {questions.map((q) => {
              const qnum = q.qnum || q.question_number || q.id;
              const title = q.title || q.question_title || `Question #${qnum}`;
              const difficulty = String(q.difficulty || "Medium").toLowerCase();
              const isSolved = Boolean(q.solved);

              return (
                <tr
                  key={qnum}
                  className="hover:bg-zinc-800/40 transition-colors group cursor-pointer"
                  onClick={() => onSelectQuestion(qnum)}
                >
                  <td className="py-3 px-4 text-xs font-mono text-zinc-500 font-medium">{qnum}</td>
                  <td className="py-3 px-4 font-medium text-zinc-200 group-hover:text-cyan-400 transition-colors">
                    {title}
                  </td>
                  <td className="py-3 px-4">
                    <Badge
                      variant={
                        difficulty === "easy" ? "easy" : difficulty === "hard" ? "hard" : "medium"
                      }
                      size="sm"
                    >
                      {difficulty.charAt(0).toUpperCase() + difficulty.slice(1)}
                    </Badge>
                  </td>
                  <td className="py-3 px-4">
                    {isSolved ? (
                      <Badge variant="solved" size="sm">
                        <CheckCircle size={12} /> Solved
                      </Badge>
                    ) : (
                      <Badge variant="unsolved" size="sm">
                        Unsolved
                      </Badge>
                    )}
                  </td>
                  <td className="py-3 px-4 text-right" onClick={(e) => e.stopPropagation()}>
                    <Link href={`/practice?qnum=${qnum}`}>
                      <Button variant="ghost" size="sm" rightIcon={<ExternalLink size={12} />}>
                        Solve
                      </Button>
                    </Link>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  }
);

QuestionTable.displayName = "QuestionTable";
