import React from "react";

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "subtle" | "glow" | "interactive";
  padding?: "none" | "sm" | "md" | "lg";
}

export const Card: React.FC<CardProps> = ({
  children,
  variant = "default",
  padding = "md",
  className = "",
  ...props
}) => {
  const baseStyles = "rounded-xl border transition-all duration-200 backdrop-blur-sm";

  const variants = {
    default: "bg-zinc-900/70 border-zinc-800/80 shadow-lg text-zinc-100",
    subtle: "bg-zinc-900/40 border-zinc-800/50 text-zinc-200",
    glow: "bg-zinc-900/80 border-cyan-500/30 shadow-[0_0_25px_-5px_rgba(6,182,212,0.15)] text-zinc-100",
    interactive: "bg-zinc-900/70 border-zinc-800/80 hover:border-zinc-700 hover:bg-zinc-800/60 hover:-translate-y-0.5 cursor-pointer text-zinc-100 shadow-md",
  };

  const paddings = {
    none: "p-0",
    sm: "p-3",
    md: "p-5",
    lg: "p-7",
  };

  return (
    <div
      className={`${baseStyles} ${variants[variant]} ${paddings[padding]} ${className}`}
      {...props}
    >
      {children}
    </div>
  );
};
