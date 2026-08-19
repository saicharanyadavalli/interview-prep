import React, { useEffect, useState } from "react";
import { Drawer } from "@/components/ui/Drawer";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { API } from "@/lib/api";
import Link from "next/link";
import { ExternalLink, CheckCircle } from "lucide-react";

export interface QuestionDrawerProps {
  qnum: number | null;
  onClose: () => void;
}

export const QuestionDrawer: React.FC<QuestionDrawerProps> = ({ qnum, onClose }) => {
  const [data, setData] = useState<any>(null);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (!qnum) return;
    setIsLoading(true);
    API.getQuestionByQnum(String(qnum))
      .then((res) => setData(res))
      .catch(() => setData(null))
      .finally(() => setIsLoading(false));
  }, [qnum]);

  return (
    <Drawer isOpen={Boolean(qnum)} onClose={onClose} title={data?.title || `Question #${qnum}`}>
      {isLoading ? (
        <div className="space-y-4">
          <Skeleton height="h-6" width="w-3/4" />
          <Skeleton height="h-24" width="w-full" />
          <Skeleton height="h-32" width="w-full" />
        </div>
      ) : data ? (
        <div className="space-y-6 text-zinc-200">
          <div className="flex items-center gap-3">
            <Badge variant={data.difficulty?.toLowerCase() === "easy" ? "easy" : "medium"}>
              {data.difficulty || "Medium"}
            </Badge>
            {data.company && <Badge variant="neutral">{data.company}</Badge>}
          </div>

          <div className="prose prose-invert max-w-none text-sm leading-relaxed bg-zinc-950/60 p-4 rounded-xl border border-zinc-800">
            <h4 className="text-xs uppercase tracking-wider text-zinc-500 font-bold mb-2">Statement</h4>
            <p>{data.statement || data.problem_description || "No detailed statement preview available."}</p>
          </div>

          <div className="pt-4 flex justify-end">
            <Link href={`/practice?qnum=${qnum}`}>
              <Button size="md" rightIcon={<ExternalLink size={14} />}>
                Open Full Practice Workspace
              </Button>
            </Link>
          </div>
        </div>
      ) : (
        <p className="text-zinc-400">Question details unavailable.</p>
      )}
    </Drawer>
  );
};
