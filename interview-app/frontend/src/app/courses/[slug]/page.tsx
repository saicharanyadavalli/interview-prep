"use client";

import React, { useEffect, useState } from "react";
import { API, CourseDetailResponse } from "@/lib/api";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, BookOpen, CheckCircle2, Circle, Play, ChevronRight, Award } from "lucide-react";
import { Spinner } from "@/components/Spinner";

export default function CourseDetailPage() {
  const params = useParams();
  const router = useRouter();
  const courseSlug = String(params.slug || "");

  const [course, setCourse] = useState<CourseDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!courseSlug) return;

    API.getCourseDetails(courseSlug)
      .then((data) => {
        setCourse(data);
        setLoading(false);
      })
      .catch((err) => {
        console.error("Failed to load course details", err);
        setError("Course not found or unavailable.");
        setLoading(false);
      });
  }, [courseSlug]);

  if (loading) {
    return (
      <main className="main-content flex items-center justify-center min-h-[60vh]">
        <Spinner />
      </main>
    );
  }

  if (error || !course) {
    return (
      <main className="main-content flex flex-col items-center justify-center min-h-[60vh]">
        <div className="card-flat p-8 max-w-md text-center">
          <h2 className="text-xl font-bold text-red-400 mb-2">Error</h2>
          <p className="text-gray-400 mb-6">{error || "Course not found."}</p>
          <Link href="/courses" className="btn btn-primary">
            <ArrowLeft size={16} /> Back to Courses
          </Link>
        </div>
      </main>
    );
  }

  const completedCount = course.completed_lessons || 0;
  const totalCount = course.total_lessons || course.lessons?.length || 0;
  const progressPercent = course.progress_percentage || 0;

  // Find next uncompleted lesson, or first lesson
  const firstUncompleted = course.lessons?.find((l) => !l.completed) || course.lessons?.[0];

  return (
    <main className="main-content animate-fade">
      {/* Back button */}
      <button
        onClick={() => router.push("/courses")}
        className="inline-flex items-center gap-2 text-sm text-gray-400 hover:text-white transition-colors mb-6 cursor-pointer"
        aria-label="Back to Courses"
      >
        <ArrowLeft size={16} /> Back to Courses
      </button>

      {/* Course Header Banner */}
      <div className="card-flat p-6 md:p-8 rounded-2xl mb-8 bg-paper/80 border border-line/60 backdrop-blur-md">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div className="flex-1">
            <div className="inline-flex items-center gap-2 text-xs font-semibold text-teal bg-teal/10 px-3 py-1 rounded-full mb-3">
              <BookOpen size={14} /> Interactive Course
            </div>
            <h1 className="text-2xl md:text-3xl font-bold text-white mb-3">{course.title}</h1>
            <p className="text-gray-300 text-sm leading-relaxed max-w-3xl mb-4">{course.description}</p>
            
            <div className="flex flex-wrap items-center gap-4 text-xs text-gray-400 font-medium">
              <span>{totalCount} Total Lessons</span>
              <span>•</span>
              <span>{completedCount} Completed</span>
            </div>
          </div>

          <div className="w-full md:w-64 bg-slate-900/60 p-4 rounded-xl border border-line/40 flex flex-col justify-center">
            <div className="flex justify-between items-center text-xs text-gray-400 mb-2 font-medium">
              <span className="flex items-center gap-1"><Award size={14} className="text-teal" /> Total Progress</span>
              <span className="text-teal font-bold text-sm">{progressPercent}%</span>
            </div>
            <div className="w-full bg-slate-800 rounded-full h-2.5 overflow-hidden mb-4 border border-line/40">
              <div
                className="bg-gradient-to-r from-teal-light to-teal h-full rounded-full transition-all duration-500"
                style={{ width: `${progressPercent}%` }}
              />
            </div>
            
            {firstUncompleted && (
              <Link
                href={`/courses/${courseSlug}/${firstUncompleted.slug}`}
                className="btn btn-primary w-full text-xs py-2 flex items-center justify-center gap-1.5 rounded-lg"
              >
                <Play size={14} fill="currentColor" /> {completedCount > 0 ? "Continue Lesson" : "Start Course"}
              </Link>
            )}
          </div>
        </div>
      </div>

      {/* Ordered Lesson Cards List */}
      <div className="mb-4">
        <h2 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
          Course Curriculum
        </h2>
        
        <div className="grid gap-3">
          {course.lessons.map((lesson) => {
            const isCompleted = Boolean(lesson.completed);
            return (
              <Link
                key={lesson.id || lesson.slug}
                href={`/courses/${courseSlug}/${lesson.slug}`}
                className={`card-flat hover-card flex items-center justify-between p-4 rounded-xl border transition-all cursor-pointer ${
                  isCompleted 
                    ? "bg-paper/40 border-teal/30 hover:border-teal/60" 
                    : "bg-paper/70 border-line/60 hover:border-line"
                }`}
              >
                <div className="flex items-center gap-4 min-w-0">
                  <div className="flex-shrink-0">
                    {isCompleted ? (
                      <CheckCircle2 size={22} className="text-teal" />
                    ) : (
                      <Circle size={22} className="text-gray-500 hover:text-gray-300" />
                    )}
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="text-xs font-semibold text-teal/80 bg-teal/10 px-2 py-0.5 rounded">
                        Lesson {lesson.order_index}
                      </span>
                    </div>
                    <h3 className="text-base font-semibold text-white truncate">{lesson.title}</h3>
                  </div>
                </div>

                <div className="flex items-center gap-2 text-xs font-semibold text-gray-400 group-hover:text-teal transition-colors ml-4 flex-shrink-0">
                  <span>{isCompleted ? "Review" : "Start"}</span>
                  <ChevronRight size={16} />
                </div>
              </Link>
            );
          })}
        </div>
      </div>
    </main>
  );
}
