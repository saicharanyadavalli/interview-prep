/**
 * learning-tracks.js - Shared learning-track metadata for frontend pages.
 */

(function initializeLearningTracks(globalScope) {
  const TRACKS = [
    {
      track_id: "system-design",
      display_name: "System Design",
      icon: "🧠",
      step_count: 30,
      qnum_base: 900000,
      assets_slug: "system-design",
      course_href: "system-design.html",
      lessons_root: "system-design/lessons",
    },
    {
      track_id: "object-oriented-design",
      display_name: "Object-Oriented Design",
      icon: "🧩",
      step_count: 14,
      qnum_base: 910000,
      assets_slug: "object-oriented-design",
      course_href: "object-oriented-design.html",
      lessons_root: "object-oriented-design/lessons",
    },
    {
      track_id: "mobile-system-design",
      display_name: "Mobile System Design",
      icon: "📱",
      step_count: 11,
      qnum_base: 920000,
      assets_slug: "mobile-system-design",
      course_href: "mobile-system-design.html",
      lessons_root: "mobile-system-design/lessons",
    },
    {
      track_id: "ml-system-design",
      display_name: "ML System Design",
      icon: "🤖",
      step_count: 11,
      qnum_base: 930000,
      assets_slug: "ml-system-design",
      course_href: "ml-system-design.html",
      lessons_root: "ml-system-design/lessons",
    },
    {
      track_id: "genai-system-design",
      display_name: "GenAI System Design",
      icon: "✨",
      step_count: 11,
      qnum_base: 940000,
      assets_slug: "genai-system-design",
      course_href: "genai-system-design.html",
      lessons_root: "genai-system-design/lessons",
    },
  ];

  const byId = TRACKS.reduce((acc, track) => {
    acc[track.track_id] = track;
    return acc;
  }, {});

  globalScope.LEARNING_TRACKS = TRACKS;
  globalScope.LEARNING_TRACKS_BY_ID = byId;

  globalScope.getLearningTrackById = function getLearningTrackById(trackId) {
    const key = String(trackId || "").trim();
    return byId[key] || null;
  };
})(window);
