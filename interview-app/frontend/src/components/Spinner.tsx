import React from "react";
import { Loader2 } from "lucide-react";

export function Spinner({ text = "Loading..." }: { text?: string }) {
  return (
    <div className="flex items-center justify-center p-8 text-muted" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem', padding: '2rem', color: 'var(--muted)' }}>
      <Loader2 className="animate-spin" size={20} />
      <span className="text-sm">{text}</span>
    </div>
  );
}
