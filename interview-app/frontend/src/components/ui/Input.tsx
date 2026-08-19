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
            <span className="absolute left-3 text-zinc-400 pointer-events-none flex items-center">
              {leftIcon}
            </span>
          )}
          <input
            ref={ref}
            className={`w-full bg-zinc-900/80 border text-zinc-100 placeholder-zinc-500 text-sm rounded-lg transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-transparent ${
              leftIcon ? "pl-9" : "pl-3.5"
            } ${rightIcon ? "pr-9" : "pr-3.5"} py-2 ${
              error ? "border-rose-500 focus:ring-rose-500" : "border-zinc-800 hover:border-zinc-700"
            } ${className}`}
            {...props}
          />
          {rightIcon && (
            <span className="absolute right-3 text-zinc-400 flex items-center">
              {rightIcon}
            </span>
          )}
        </div>
        {error && <p className="mt-1 text-xs text-rose-400">{error}</p>}
      </div>
    );
  }
);

Input.displayName = "Input";
