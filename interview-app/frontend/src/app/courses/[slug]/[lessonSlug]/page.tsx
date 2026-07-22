"use client";

import React, { useEffect, useState } from "react";
import {
  API,
  LessonDetailResponse,
  CourseDetailResponse,
  SeedTableDefinition,
} from "@/lib/api";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  CheckCircle2,
  Circle,
  ChevronRight,
  ChevronLeft,
  BookOpen,
  List,
  CheckSquare,
  Square,
  Award,
  Sparkles,
  Menu,
  X,
} from "lucide-react";
import { Spinner } from "@/components/Spinner";
import { MarkdownRenderer } from "@/components/courses/MarkdownRenderer";
import { SqlRunner } from "@/components/courses/SqlRunner";

export default function LessonPage() {
  const params = useParams();
  const router = useRouter();
  const courseSlug = String(params.slug || "");
  const lessonSlug = String(params.lessonSlug || "");

  const [lesson, setLesson] = useState<LessonDetailResponse | null>(null);
  const [course, setCourse] = useState<CourseDetailResponse | null>(null);
  const [seedTables, setSeedTables] = useState<SeedTableDefinition[]>([]);
  const [checkedTasks, setCheckedTasks] = useState<Record<number, boolean>>({});
  const [isCompleted, setIsCompleted] = useState(false);

  const [loading, setLoading] = useState(true);
  const [completing, setCompleting] = useState(false);
  const [error, setError] = useState("");
  const [showNavDrawer, setShowNavDrawer] = useState(false);

  useEffect(() => {
    if (!courseSlug || !lessonSlug) return;

    setLoading(true);
    setError("");

    Promise.allSettled([
      API.getLesson(courseSlug, lessonSlug),
      API.getCourseDetails(courseSlug),
      API.getCourseSeedTables(courseSlug),
    ]).then(([lessonRes, courseRes, seedRes]) => {
      if (lessonRes.status === "fulfilled") {
        const l = lessonRes.value;
        setLesson(l);
        setIsCompleted(Boolean(l.completed));
        // Reset task check states
        const initialTasks: Record<number, boolean> = {};
        if (l.tasks) {
          l.tasks.forEach((_, idx) => {
            initialTasks[idx] = Boolean(l.completed);
          });
        }
        setCheckedTasks(initialTasks);
      } else {
        setError("Lesson not found or failed to load.");
      }

      if (courseRes.status === "fulfilled") {
        setCourse(courseRes.value);
      }

      if (seedRes.status === "fulfilled" && seedRes.value?.tables) {
        setSeedTables(seedRes.value.tables);
      }

      setLoading(false);
    });
  }, [courseSlug, lessonSlug]);

  const toggleTask = (index: number) => {
    setCheckedTasks((prev) => ({
      ...prev,
      [index]: !prev[index],
    }));
  };

  const handleMarkComplete = async () => {
    if (completing || !lesson) return;
    setCompleting(true);

    try {
      const res = await API.completeLesson(courseSlug, lessonSlug);
      if (res && res.success) {
        setIsCompleted(true);
        // Mark all tasks as checked
        if (lesson.tasks) {
          const allChecked: Record<number, boolean> = {};
          lesson.tasks.forEach((_, i) => {
            allChecked[i] = true;
          });
          setCheckedTasks(allChecked);
        }

        // Update course progress count locally
        if (course) {
          setCourse({
            ...course,
            completed_lessons: res.course_progress.completed_lessons,
            progress_percentage: res.course_progress.progress_percentage,
            lessons: course.lessons.map((l) =>
              l.slug === lessonSlug ? { ...l, completed: true } : l
            ),
          });
        }
      }
    } catch (err: any) {
      console.error("Failed to complete lesson:", err);
      // Fallback: update UI state anyway
      setIsCompleted(true);
    } finally {
      setCompleting(false);
    }
  };

  if (loading) {
    return (
      <main className="main-content flex items-center justify-center min-h-[60vh]">
        <Spinner />
      </main>
    );
  }

  if (error || !lesson) {
    return (
      <main className="main-content flex flex-col items-center justify-center min-h-[60vh]">
        <div className="card-flat p-8 max-w-md text-center">
          <h2 className="text-xl font-bold text-red-400 mb-2 font-mono">Error</h2>
          <p className="text-gray-400 mb-6">{error || "Lesson not found."}</p>
          <Link href={`/courses/${courseSlug}`} className="btn btn-primary">
            <ArrowLeft size={16} /> Back to Course
          </Link>
        </div>
      </main>
    );
  }

  const isSqlCourse = courseSlug === "sql-course" || courseSlug === "sql";

  const allTasksChecked =
    isSqlCourse && lesson.tasks && lesson.tasks.length > 0
      ? lesson.tasks.every((_, i) => checkedTasks[i])
      : false;

  return (
    <main className="main-content animate-fade relative pb-12">
      {/* Top Header & Navigation Bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 mb-6 pb-4 border-b border-line/50">
        <div className="flex items-center gap-3">
          <button
            onClick={() => router.push(`/courses/${courseSlug}`)}
            className="btn btn-sm btn-secondary flex items-center gap-1.5 text-xs text-gray-300 hover:text-white"
            aria-label="Back to Course"
          >
            <ArrowLeft size={14} /> Course Overview
          </button>

          {/* Drawer toggle for small screens */}
          {course?.lessons && course.lessons.length > 0 && (
            <button
              onClick={() => setShowNavDrawer(!showNavDrawer)}
              className="btn btn-sm btn-secondary flex items-center gap-1 text-xs text-teal lg:hidden"
            >
              <List size={14} /> Curriculum ({course.lessons.length})
            </button>
          )}
        </div>

        {/* Course Progress Pill */}
        {course && (
          <div className="flex items-center gap-3 text-xs">
            <span className="text-gray-400 font-medium hidden sm:inline">
              {course.title}
            </span>
            <div className="flex items-center gap-2 bg-slate-900/80 px-3 py-1 rounded-full border border-line/40">
              <Award size={14} className="text-teal" />
              <span className="text-teal font-bold">{course.progress_percentage || 0}%</span>
            </div>
          </div>
        )}
      </div>

      {/* Main 2-Column Grid Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Navigator Sidebar (Desktop) */}
        {course?.lessons && (
          <aside className={`lg:col-span-3 ${showNavDrawer ? "block" : "hidden lg:block"} card-flat p-4 rounded-xl border border-line/60 bg-paper/80 backdrop-blur-md`}>
            <div className="flex items-center justify-between mb-3 pb-2 border-b border-line/40">
              <h3 className="text-xs font-bold text-gray-300 uppercase tracking-wider flex items-center gap-1.5">
                <BookOpen size={14} className="text-teal" /> Lessons
              </h3>
              <button
                onClick={() => setShowNavDrawer(false)}
                className="lg:hidden text-gray-400 hover:text-white"
              >
                <X size={16} />
              </button>
            </div>

            <div className="flex flex-col gap-1 max-h-[70vh] overflow-y-auto pr-1">
              {course.lessons.map((item) => {
                const isActive = item.slug === lessonSlug;
                const isItemCompleted = Boolean(item.completed);

                return (
                  <Link
                    key={item.id || item.slug}
                    href={`/courses/${courseSlug}/${item.slug}`}
                    onClick={() => setShowNavDrawer(false)}
                    className={`flex items-center justify-between p-2.5 rounded-lg text-xs transition-all ${
                      isActive
                        ? "bg-teal/20 text-teal font-semibold border border-teal/40"
                        : "text-gray-300 hover:bg-slate-800/60 hover:text-white"
                    }`}
                  >
                    <div className="flex items-center gap-2 min-w-0 pr-2">
                      <span className="text-gray-500 font-mono text-[11px] flex-shrink-0">
                        #{item.order_index}
                      </span>
                      <span className="truncate">{item.title}</span>
                    </div>
                    {isItemCompleted ? (
                      <CheckCircle2 size={14} className="text-teal flex-shrink-0" />
                    ) : (
                      <Circle size={14} className="text-gray-600 flex-shrink-0" />
                    )}
                  </Link>
                );
              })}
            </div>
          </aside>
        )}

        {/* Content & Editor Area */}
        <div className={`grid grid-cols-1 ${course?.lessons ? "lg:col-span-9" : "lg:col-span-12"} gap-6`}>
          {/* Main Lesson Content Column */}
          <div className="flex flex-col gap-6 w-full">
            {/* Lesson Header Banner */}
            <div className="card-flat p-6 rounded-2xl border border-line/60 bg-paper/80 w-full max-w-none mx-auto">
              <div className="flex items-center justify-between gap-3 mb-2">
                <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-teal bg-teal/10 px-2.5 py-1 rounded-full">
                  Lesson {lesson.order_index}
                </span>
                {isCompleted && (
                  <span className="inline-flex items-center gap-1 text-xs font-semibold text-teal bg-teal/10 px-3 py-1 rounded-full border border-teal/20">
                    <CheckCircle2 size={14} /> Completed
                  </span>
                )}
              </div>
              <h1 className="text-2xl font-bold text-white mb-2">{lesson.title}</h1>
            </div>

            {/* Markdown Content Block */}
            <div className="card-flat p-6 md:p-10 rounded-2xl border border-line/60 bg-paper/80 shadow-md w-full max-w-none mx-auto transition-all">
              <MarkdownRenderer content={lesson.content_markdown} />
            </div>

            {/* Exercise Tasks Section — Only for SQL Course */}
            {isSqlCourse && lesson.tasks && lesson.tasks.length > 0 && (
              <div className="card-flat p-6 rounded-2xl border border-line/60 bg-paper/80 w-full max-w-none mx-auto">
                <h3 className="text-base font-bold text-white mb-3 flex items-center gap-2">
                  <CheckSquare size={18} className="text-teal" /> Lesson Exercises &amp; Tasks
                </h3>
                <p className="text-xs text-gray-400 mb-4">
                  Complete the exercises in the SQL Query runner, then check off each item below:
                </p>

                <div className="space-y-2.5">
                  {lesson.tasks.map((task, idx) => {
                    const isChecked = Boolean(checkedTasks[idx]);
                    return (
                      <div
                        key={idx}
                        onClick={() => toggleTask(idx)}
                        className={`flex items-start gap-3 p-3 rounded-xl border transition-all cursor-pointer ${
                          isChecked
                            ? "bg-teal-soft/10 border-teal/30 text-teal-light"
                            : "bg-slate-900/60 border-line/40 text-gray-300 hover:border-line"
                        }`}
                      >
                        <button
                          type="button"
                          className="mt-0.5 text-teal focus:outline-none flex-shrink-0"
                          aria-label={isChecked ? "Uncheck task" : "Check task"}
                        >
                          {isChecked ? (
                            <CheckSquare size={18} className="text-teal" />
                          ) : (
                            <Square size={18} className="text-gray-500" />
                          )}
                        </button>
                        <span className={`text-sm leading-relaxed ${isChecked ? "line-through opacity-80" : ""}`}>
                          <strong className="text-teal font-semibold mr-1 font-mono">{idx + 1}.</strong> {task}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* SQL Runner Component — Only for SQL Course */}
            {isSqlCourse && (
              <div className="mt-2 w-full max-w-none mx-auto">
                <SqlRunner seedTables={seedTables} />
              </div>
            )}

            {/* Bottom Actions & Completion Bar */}
            <div className="card-flat p-6 rounded-2xl border border-line/60 bg-paper/90 flex flex-wrap items-center justify-between gap-4 mt-2">
              <div className="flex items-center gap-3">
                {lesson.prev_lesson_slug ? (
                  <Link
                    href={`/courses/${courseSlug}/${lesson.prev_lesson_slug}`}
                    className="btn btn-secondary flex items-center gap-1.5 text-xs py-2 px-3"
                  >
                    <ChevronLeft size={16} /> Previous Lesson
                  </Link>
                ) : (
                  <Link
                    href={`/courses/${courseSlug}`}
                    className="btn btn-secondary flex items-center gap-1.5 text-xs py-2 px-3"
                  >
                    <ArrowLeft size={16} /> Course Details
                  </Link>
                )}
              </div>

              <div className="flex items-center gap-3">
                <button
                  onClick={handleMarkComplete}
                  disabled={completing}
                  className={`btn ${isCompleted ? "btn-secondary border-teal/40 text-teal" : "btn-primary"} flex items-center gap-2 py-2 px-4 rounded-xl transition-all`}
                >
                  {completing ? (
                    <Spinner />
                  ) : isCompleted ? (
                    <>
                      <CheckCircle2 size={16} className="text-teal" /> Completed
                    </>
                  ) : (
                    <>
                      <Sparkles size={16} /> Mark Lesson Complete
                    </>
                  )}
                </button>

                {lesson.next_lesson_slug ? (
                  <Link
                    href={`/courses/${courseSlug}/${lesson.next_lesson_slug}`}
                    className="btn btn-primary flex items-center gap-1.5 text-xs py-2 px-4 rounded-xl"
                  >
                    Next Lesson <ChevronRight size={16} />
                  </Link>
                ) : (
                  <Link
                    href={`/courses/${courseSlug}`}
                    className="btn btn-secondary flex items-center gap-1.5 text-xs py-2 px-4 rounded-xl text-teal"
                  >
                    Course Finished <CheckCircle2 size={16} />
                  </Link>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
