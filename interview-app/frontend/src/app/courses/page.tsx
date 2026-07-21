"use client";

import React, { useEffect, useState } from "react";
import { API, CourseSummary } from "@/lib/api";
import Link from "next/link";
import { BookOpen, Database, CheckCircle2, Play, ArrowRight, Sparkles } from "lucide-react";
import { Spinner } from "@/components/Spinner";

export default function CoursesPage() {
  const [courses, setCourses] = useState<CourseSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    API.getCourses()
      .then((data) => {
        setCourses(data || []);
        setLoading(false);
      })
      .catch((err) => {
        console.error("Failed to load courses", err);
        setError("Failed to load available courses.");
        setLoading(false);
      });
  }, []);

  if (loading) {
    return (
      <main className="main-content flex items-center justify-center min-h-[60vh]">
        <Spinner />
      </main>
    );
  }

  return (
    <main className="main-content animate-fade">
      {/* Header section */}
      <div className="page-header mb-8">
        <div>
          <h1 className="flex items-center gap-3 text-2xl font-bold text-white mb-2">
            <BookOpen size={30} className="text-teal" /> Interactive Courses
          </h1>
          <p className="text-gray-400 text-sm max-w-2xl">
            Master databases, system design, and algorithms through interactive lessons and in-browser execution runtimes.
          </p>
        </div>
      </div>

      {error ? (
        <div className="card-flat p-6 text-center text-red-400">
          <p>{error}</p>
        </div>
      ) : courses.length === 0 ? (
        <div className="card-flat p-8 text-center text-gray-400">
          <Sparkles size={36} className="mx-auto text-teal mb-3" />
          <h3 className="text-lg font-semibold text-white mb-1">No Courses Available</h3>
          <p className="text-sm">Check back soon for newly published interactive courses!</p>
        </div>
      ) : (
        <div className="grid gap-6 grid-cols-1 md:grid-cols-2">
          {courses.map((course, idx) => {
            const completedCount = course.completed_lessons || 0;
            const totalCount = course.total_lessons || 0;
            const progress = course.progress_percentage || 0;
            const isStarted = progress > 0;

            return (
              <div
                key={course.id || course.slug}
                className="card-flat hover-card flex flex-col justify-between p-6 rounded-2xl border border-line/60 bg-paper/60 backdrop-blur-md animate-slide transition-all"
                style={{ animationDelay: `${idx * 80}ms` }}
              >
                <div>
                  <div className="flex items-center justify-between mb-4">
                    <div className="p-3 rounded-xl bg-teal-soft/20 text-teal border border-teal/20">
                      <Database size={24} />
                    </div>
                    {isStarted && (
                      <span className="inline-flex items-center gap-1 text-xs font-semibold text-teal bg-teal/10 px-3 py-1 rounded-full">
                        <CheckCircle2 size={14} /> {progress}% Completed
                      </span>
                    )}
                  </div>

                  <h2 className="text-xl font-bold text-white mb-2">{course.title}</h2>
                  <p className="text-sm text-gray-400 leading-relaxed mb-6">
                    {course.description}
                  </p>
                </div>

                <div>
                  {/* Progress Bar */}
                  <div className="mb-5">
                    <div className="flex justify-between text-xs text-gray-400 mb-1.5 font-medium">
                      <span>{completedCount} of {totalCount} lessons</span>
                      <span className="text-teal font-semibold">{progress}%</span>
                    </div>
                    <div className="w-full bg-slate-800/80 rounded-full h-2 overflow-hidden border border-line/40">
                      <div
                        className="bg-gradient-to-r from-teal-light to-teal h-full rounded-full transition-all duration-500"
                        style={{ width: `${progress}%` }}
                      />
                    </div>
                  </div>

                  <Link
                    href={`/courses/${course.slug}`}
                    className={`btn ${isStarted ? "btn-primary" : "btn-secondary"} w-full flex items-center justify-center gap-2 py-2.5 font-medium rounded-xl transition-all`}
                    aria-label={`${isStarted ? "Continue" : "Start"} course ${course.title}`}
                  >
                    {isStarted ? (
                      <>
                        <Play size={16} fill="currentColor" /> Continue Course
                      </>
                    ) : (
                      <>
                        Start Course <ArrowRight size={16} />
                      </>
                    )}
                  </Link>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </main>
  );
}
