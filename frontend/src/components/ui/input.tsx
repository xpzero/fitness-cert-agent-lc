import * as React from "react";
import { cn } from "@/lib/utils";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "w-full rounded-lg border border-input bg-white px-3 py-2 text-[13px] outline-none",
        "focus-visible:ring-2 focus-visible:ring-ring placeholder:text-muted-foreground",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        "w-full rounded-lg border border-input bg-white px-3 py-2 text-[13px] outline-none",
        "focus-visible:ring-2 focus-visible:ring-ring placeholder:text-muted-foreground",
        className,
      )}
      {...props}
    />
  ),
);
Textarea.displayName = "Textarea";

export function Progress({ value, className, tone = "primary" }: { value: number; className?: string; tone?: "primary" | "success" }) {
  return (
    <div className={cn("h-[7px] w-full overflow-hidden rounded-full bg-secondary", className)}>
      <div
        className={cn("h-full rounded-full transition-all", tone === "primary" ? "bg-primary" : "bg-[var(--success)]")}
        style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
      />
    </div>
  );
}
