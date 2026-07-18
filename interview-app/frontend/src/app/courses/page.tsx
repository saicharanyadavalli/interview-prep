"use client";

import React, { useEffect, useState } from "react";
import { API } from "@/lib/api";
import Link from "next/link";
import { BookOpen, Layers } from "lucide-react";
import { Spinner } from "@/components/Spinner";

export default function CoursesPage() {
  const [tracks, setTracks] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    API.getLearningTracks()
      .then((res) => {
        setTracks(res.tracks || []);
        setLoading(false);
      })
      .catch((err) => {
        console.error("Failed to load tracks", err);
        setLoading(false);
      });
  }, []);

  if (loading) {
    return (
      <main className="main-content flex items-center justify-center">
        <Spinner />
      </main>
    );
  }

  return (
    <main className="main-content">
      <div className="page-header">
        <h1 style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <BookOpen size={28} className="text-teal" /> Courses
        </h1>
        <p className="text-gray-400 mt-2">Master system design and architecture.</p>
      </div>

      <div className="stats-grid mt-6" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))' }}>
        {tracks.map((track, idx) => (
          <Link 
            key={track.track_id} 
            href={`/courses/${track.track_id}`} 
            className="card-flat hover-card animate-slide"
            style={{ animationDelay: `${idx * 50}ms`, textDecoration: 'none', display: 'block' }}
          >
            <div className="flex items-start gap-4">
              <div className="bg-teal/10 p-3 rounded-lg text-teal">
                <Layers size={24} />
              </div>
              <div>
                <h3 className="text-lg font-semibold text-white mb-1">{track.display_name}</h3>
                <p className="text-sm text-gray-400">{track.step_count} chapters</p>
              </div>
            </div>
          </Link>
        ))}
      </div>
    </main>
  );
}
