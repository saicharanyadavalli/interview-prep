"use client";

import React, { useEffect, useState } from "react";
import { API } from "@/lib/api";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Layers, CheckCircle2, Circle } from "lucide-react";
import { Spinner } from "@/components/Spinner";

export default function TrackPage() {
  const params = useParams();
  const router = useRouter();
  const trackId = String(params.track || "");
  
  const [progress, setProgress] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!trackId) return;

    API.getLearningTrackProgress(trackId)
      .then((res) => {
        setProgress(res);
        setLoading(false);
      })
      .catch((err) => {
        console.error("Failed to load track", err);
        setError("Track not found");
        setLoading(false);
      });
  }, [trackId]);

  const toggleStepCompletion = (e: React.MouseEvent, stepNo: number, currentCompleted: boolean) => {
    e.preventDefault();
    e.stopPropagation();
    
    const newStatus = !currentCompleted;
    
    // Optimistic update
    setProgress((prev: any) => {
      if (!prev) return prev;
      const newSteps = prev.steps.map((s: any) => 
        s.step_no === stepNo ? { ...s, completed: newStatus } : s
      );
      const newCompletedCount = newSteps.filter((s: any) => s.completed).length;
      const newPercent = prev.total_steps ? Math.round((newCompletedCount / prev.total_steps) * 100) : 0;
      
      return {
        ...prev,
        steps: newSteps,
        completed_steps: newCompletedCount,
        completion_percent: newPercent
      };
    });

    API.updateLearningTrackProgress(trackId, stepNo, newStatus)
      .catch((err) => {
        console.error("Failed to update progress", err);
        // Revert on error
        API.getLearningTrackProgress(trackId).then(setProgress).catch(console.error);
      });
  };

  if (loading) {
    return (
      <main className="main-content flex items-center justify-center">
        <Spinner />
      </main>
    );
  }

  if (error || !progress) {
    return (
      <main className="main-content flex flex-col items-center justify-center">
        <h2 className="text-2xl font-bold text-red-500 mb-4">Error</h2>
        <p className="text-gray-400 mb-6">{error}</p>
        <button onClick={() => router.push("/courses")} className="btn btn-primary">
          Back to Courses
        </button>
      </main>
    );
  }

  return (
    <main className="main-content">
      <div className="page-header mb-8">
        <button 
          onClick={() => router.push("/courses")}
          className="mb-4 text-sm text-gray-500 hover:text-white transition-colors block"
        >
          &larr; Back to Courses
        </button>
        <h1 style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', textTransform: 'capitalize' }}>
          <Layers size={28} className="text-teal" /> {trackId.split('-').join(' ')}
        </h1>
        
        <div className="mt-6 bg-surface p-4 rounded-xl border border-border/50">
          <div className="flex justify-between text-sm mb-2">
            <span className="text-gray-400">Course Progress</span>
            <span className="text-teal font-semibold">{progress.completion_percent}%</span>
          </div>
          <div className="w-full bg-background rounded-full h-2.5">
            <div className="bg-teal h-2.5 rounded-full" style={{ width: `${progress.completion_percent}%` }}></div>
          </div>
          <p className="text-xs text-gray-500 mt-2">
            {progress.completed_steps} of {progress.total_steps} chapters completed
          </p>
        </div>
      </div>

      <div className="grid gap-3">
        {progress.steps.map((step: any) => (
          <div 
            key={step.step_no} 
            onClick={() => router.push(`/courses/${trackId}/lessons/${step.step_no}`)}
            className="card-flat hover-card flex items-center p-4 transition-all cursor-pointer"
          >
            <div className="mr-4">
              <button 
                onClick={(e) => toggleStepCompletion(e, step.step_no, step.completed)}
                className="focus:outline-none flex items-center justify-center rounded-full transition-colors hover:bg-white/10 p-1"
                aria-label={step.completed ? "Mark as uncompleted" : "Mark as completed"}
                title={step.completed ? "Mark as uncompleted" : "Mark as completed"}
              >
                {step.completed ? (
                  <CheckCircle2 size={24} className="text-teal" />
                ) : (
                  <Circle size={24} className="text-gray-600 hover:text-gray-400" />
                )}
              </button>
            </div>
            <div>
              <p className="text-sm text-gray-400 mb-1">Chapter {step.step_no}</p>
              <h3 className="text-lg font-medium text-white">{step.title}</h3>
            </div>
          </div>
        ))}
      </div>
    </main>
  );
}
