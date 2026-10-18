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
    default: "bg-paper border-line shadow-lg text-ink",
    subtle: "bg-surface-soft border-line/60 text-ink",
    glow: "bg-paper border-teal/40 shadow-[0_0_25px_-5px_rgba(15,118,110,0.15)] text-ink",
    interactive: "bg-paper border-line hover:border-teal/50 hover:bg-sidebar-hover hover:-translate-y-0.5 cursor-pointer text-ink shadow-md",
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
