"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { API } from "@/lib/api";
import { BookOpen, ArrowLeft } from "lucide-react";

export default function LessonPage() {
  const params = useParams();
  const router = useRouter();
  const track = String(params.track || "");
  const step = Number(params.step || 0);

  const [lesson, setLesson] = useState<{ title: string; html_content: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!track || !step) return;

    let isMounted = true;
    setLoading(true);
    setError("");

    API.getLearningTrackLesson(track, step)
      .then((data) => {
        if (isMounted) {
          setLesson(data);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (isMounted) {
          setError(err.message || "Failed to load lesson");
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [track, step]);

  if (loading) {
    return (
      <main className="main-content flex items-center justify-center min-h-[50vh]">
        <div className="animate-spin h-8 w-8 border-4 border-teal border-t-transparent rounded-full"></div>
      </main>
    );
  }

  if (error || !lesson) {
    return (
      <main className="main-content flex flex-col items-center justify-center min-h-[50vh]">
        <h2 className="text-2xl font-bold text-red-500 mb-4">Oops!</h2>
        <p className="text-gray-400 mb-6">{error || "Lesson not found."}</p>
        <button
          onClick={() => router.back()}
          className="btn btn-primary flex items-center gap-2"
        >
          <ArrowLeft size={18} /> Go Back
        </button>
      </main>
    );
  }

  return (
    <main className="main-content">
      <div className="page-header mb-8 flex justify-between items-center w-full">
        <h1 style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <BookOpen size={28} className="text-teal" /> {lesson.title || `Chapter ${step}`}
        </h1>
        <button 
          onClick={() => router.back()}
          className="btn btn-sm"
          style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
        >
          <ArrowLeft size={16} /> Back to {track.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')}
        </button>
      </div>

      <div className="section p-6 sm:p-12">
        <style dangerouslySetInnerHTML={{ __html: `
          .lesson-content {
            width: 100%;
            overflow-wrap: break-word;
            word-wrap: break-word;
            word-break: break-word;
          }
          .lesson-content * {
            max-width: 100% !important;
            box-sizing: border-box !important;
            margin-left: 0 !important;
            margin-right: 0 !important;
            left: 0 !important;
            right: 0 !important;
            position: relative !important;
          }
          .lesson-content img, .lesson-content figure, .lesson-content video {
            max-width: 100% !important;
            height: auto !important;
            object-fit: contain !important;
            display: block;
            margin: 1.5rem auto !important;
            border-radius: 0.5rem;
          }
          .lesson-content pre, .lesson-content code {
            white-space: pre-wrap !important;
            overflow-x: auto !important;
            max-width: 100% !important;
          }
        `}} />

        <div 
          className="prose prose-invert prose-lg max-w-none lesson-content text-gray-300 leading-relaxed"
          dangerouslySetInnerHTML={{ __html: lesson.html_content }} 
        />
      </div>
    </main>
  );
}
