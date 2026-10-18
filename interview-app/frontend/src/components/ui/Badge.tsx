import React from "react";

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: "easy" | "medium" | "hard" | "solved" | "unsolved" | "revisit" | "neutral" | "cyan";
  size?: "sm" | "md";
}

export const Badge: React.FC<BadgeProps> = ({
  children,
  variant = "neutral",
  size = "md",
  className = "",
  ...props
}) => {
  const baseStyles = "inline-flex items-center font-medium rounded-full border transition-colors";

  const variants = {
    easy: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/25",
    medium: "bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/25",
    hard: "bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-500/25",
    solved: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/35",
    unsolved: "bg-zinc-200/80 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-400 border-zinc-300 dark:border-zinc-700/50",
    revisit: "bg-indigo-500/10 text-indigo-700 dark:text-indigo-400 border-indigo-500/25",
    cyan: "bg-teal-500/10 text-teal-800 dark:text-cyan-400 border-teal-500/25",
    neutral: "bg-zinc-200/70 dark:bg-zinc-800/80 text-zinc-700 dark:text-zinc-300 border-zinc-300 dark:border-zinc-700/60",
  };

  const sizes = {
    sm: "px-2 py-0.5 text-[11px] gap-1",
    md: "px-2.5 py-1 text-xs gap-1.5",
  };

  return (
    <span
      className={`${baseStyles} ${variants[variant]} ${sizes[size]} ${className}`}
      {...props}
    >
      {children}
    </span>
  );
};
