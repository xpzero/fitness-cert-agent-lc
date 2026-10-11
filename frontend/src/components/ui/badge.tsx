import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11.5px] font-semibold",
  {
    variants: {
      variant: {
        default: "bg-secondary text-secondary-foreground",
        ok: "bg-green-100 text-green-700",
        warn: "bg-amber-100 text-amber-700",
        bad: "bg-red-100 text-red-700",
        info: "bg-sky-100 text-sky-700",
        outline: "border border-border text-muted-foreground",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export function Badge({
  className,
  variant,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & VariantProps<typeof badgeVariants>) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export function Dot({ tone }: { tone: "ok" | "parsing" | "fail" }) {
  return (
    <span
      className={cn("h-[7px] w-[7px] rounded-full", {
        "bg-green-500": tone === "ok",
        "bg-amber-500": tone === "parsing",
        "bg-red-500": tone === "fail",
      })}
    />
  );
}
