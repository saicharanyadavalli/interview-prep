import React from "react";

function normalizeTopicKey(value: string) {
  return String(value || "").trim().toLowerCase();
}

function buildTopicDifficultyRow(label: string, solvedValue: number, totalValue: number, className: string) {
  const solved = Number(solvedValue || 0);
  const total = Number(totalValue || 0);
  const percent = total > 0 ? Math.round((solved / total) * 100) : 0;

  const colorStyles: Record<string, string> = {
    easy: "var(--teal)",
    medium: "var(--amber)",
    hard: "var(--red)",
  };
  const color = colorStyles[className] || "var(--teal)";

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.85rem' }}>
        <span style={{ fontWeight: 500, color: 'var(--muted)' }}>{label}</span>
        <span style={{ color: 'var(--muted)' }}>
          <span style={{ color: 'var(--ink)', fontWeight: 500, marginRight: '0.25rem' }}>{solved}</span>/ {total} <span style={{ margin: '0 0.25rem' }}>•</span> {percent}%
        </span>
      </div>
      <div style={{ width: '100%', backgroundColor: 'var(--line)', borderRadius: '9999px', height: '6px', overflow: 'hidden' }}>
        <div style={{ height: '100%', borderRadius: '9999px', width: `${percent}%`, backgroundColor: color }}></div>
      </div>
    </div>
  );
}

function renderTopicDetailCard(topicData: any) {
  return (
    <div 
      className="bg-surface border border-line" 
      style={{ 
        padding: '1.25rem', 
        borderRadius: 'var(--radius-lg)', 
        marginTop: '0.5rem', 
        width: '100%', 
        maxWidth: '42rem',
        backgroundColor: 'var(--paper)'
      }}
    >
      <div className="flex justify-between items-center mb-3 pb-3 border-b border-line">
        <h4 className="font-semibold text-base text-white">{topicData.topic || "Topic Detail"}</h4>
        <div className="text-sm">
          <span className="text-teal font-medium mr-1">{Number(topicData.solved_questions || 0)}</span>
          <span className="text-gray-400">/ {Number(topicData.total_questions || 0)} solved</span>
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        {buildTopicDifficultyRow("Easy", topicData.easy_solved_questions, topicData.easy_total_questions, "easy")}
        {buildTopicDifficultyRow("Medium", topicData.medium_solved_questions, topicData.medium_total_questions, "medium")}
        {buildTopicDifficultyRow("Hard", topicData.hard_solved_questions, topicData.hard_total_questions, "hard")}
      </div>
    </div>
  );
}

export function TopicInsights({
  topicBreakdown,
  allTopicData,
  activeTopicKey,
  onTopicSelect
}: {
  topicBreakdown: any[];
  allTopicData: any;
  activeTopicKey: string;
  onTopicSelect: (key: string) => void;
}) {
  const topics = Array.isArray(topicBreakdown) ? topicBreakdown : [];
  const normalizedActiveKey = normalizeTopicKey(activeTopicKey || "all") || "all";

  const activeTopic = normalizedActiveKey === "all"
    ? allTopicData
    : (topics.find((item) => normalizeTopicKey(item.topic_key) === normalizedActiveKey) || allTopicData);

  return (
    <>
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold">Topic Insights</h3>
        {normalizedActiveKey === "all" && (
          <span className="text-sm text-gray-400">
            {activeTopic.topic} • <span className="text-white mx-1">{Number(activeTopic.solved_questions || 0)}</span>/ {Number(activeTopic.total_questions || 0)} solved
          </span>
        )}
      </div>
      <div className="flex flex-wrap gap-2 mb-4">
        <button 
          type="button" 
          className={`px-3 py-1.5 rounded-full border text-sm flex items-center transition-colors ${
            normalizedActiveKey === "all" 
              ? "bg-teal/20 border-teal/50 text-teal" 
              : "bg-surface border-border/50 text-gray-400 hover:text-white hover:bg-border/30"
          }`}
          style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}
          onClick={() => onTopicSelect("all")}
        >
          All Topics{" "}
          <span className={normalizedActiveKey === "all" ? "text-teal font-medium" : "text-gray-500"}>
            {Number(allTopicData.solved_questions || 0)} / {Number(allTopicData.total_questions || 0)}
          </span>
        </button>
        {topics.map((topic) => {
          const key = normalizeTopicKey(topic.topic_key);
          const solved = Number(topic.solved_questions || 0);
          const total = Number(topic.total_questions || 0);
          const isActive = normalizedActiveKey === key;
          return (
            <button 
              key={key}
              type="button" 
              className={`px-3 py-1.5 rounded-full border text-sm flex items-center transition-colors ${
                isActive 
                  ? "bg-teal/20 border-teal/50 text-teal" 
                  : "bg-surface border-border/50 text-gray-400 hover:text-white hover:bg-border/30"
              }`}
              style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}
              onClick={() => onTopicSelect(key)}
            >
              {topic.topic || "Untitled"}{" "}
              <span className={isActive ? "text-teal font-medium" : "text-gray-500"}>
                {solved} / {total}
              </span>
            </button>
          );
        })}
      </div>
      {normalizedActiveKey !== "all" && (
        <div className="w-full">
          {renderTopicDetailCard(activeTopic)}
        </div>
      )}
    </>
  );
}
