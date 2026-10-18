import React from "react";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "outline" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
  isLoading?: boolean;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
}

export const Button: React.FC<ButtonProps> = ({
  children,
  variant = "primary",
  size = "md",
  isLoading = false,
  leftIcon,
  rightIcon,
  className = "",
  disabled,
  ...props
}) => {
  const baseStyles = "inline-flex items-center justify-center font-medium transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 disabled:opacity-50 disabled:pointer-events-none active:scale-[0.98]";
  
  const variants = {
    primary: "bg-teal hover:bg-teal-light text-white shadow-sm shadow-teal-900/30",
    secondary: "bg-surface-chip hover:bg-surface-soft text-ink border border-line",
    outline: "border border-line hover:bg-sidebar-hover text-ink",
    ghost: "hover:bg-sidebar-hover text-muted hover:text-ink",
    danger: "bg-rose-600 hover:bg-rose-500 text-white shadow-sm",
  };

  const sizes = {
    sm: "px-3 py-1.5 text-xs rounded-md gap-1.5",
    md: "px-4 py-2 text-sm rounded-lg gap-2",
    lg: "px-6 py-3 text-base rounded-xl gap-2.5",
  };

  return (
    <button
      className={`${baseStyles} ${variants[variant]} ${sizes[size]} ${className}`}
      disabled={disabled || isLoading}
      {...props}
    >
      {isLoading ? <span className="animate-spin rounded-full h-4 w-4 border-2 border-white border-t-transparent mr-2" /> : leftIcon}
      {children}
      {!isLoading && rightIcon}
    </button>
  );
};
