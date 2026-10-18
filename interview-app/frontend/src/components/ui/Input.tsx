import React from "react";

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
  error?: string;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ leftIcon, rightIcon, error, className = "", ...props }, ref) => {
    return (
      <div className="w-full">
        <div className="relative flex items-center">
          {leftIcon && (
            <span className="absolute left-3 text-muted pointer-events-none flex items-center">
              {leftIcon}
            </span>
          )}
          <input
            ref={ref}
            className={`w-full bg-paper border text-ink placeholder:text-muted text-sm rounded-lg transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-teal focus:border-transparent ${
              leftIcon ? "pl-9" : "pl-3.5"
            } ${rightIcon ? "pr-9" : "pr-3.5"} py-2 ${
              error ? "border-red focus:ring-red" : "border-line hover:border-teal/50"
            } ${className}`}
            {...props}
          />
          {rightIcon && (
            <span className="absolute right-3 text-muted flex items-center">
              {rightIcon}
            </span>
          )}
        </div>
        {error && <p className="mt-1 text-xs text-red">{error}</p>}
      </div>
    );
  }
);

Input.displayName = "Input";
