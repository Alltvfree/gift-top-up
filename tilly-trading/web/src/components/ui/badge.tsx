import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded border px-1.5 py-0.5 font-mono text-[10px]",
  {
    variants: {
      tone: {
        up: "border-up/25 bg-up/15 text-up",
        down: "border-down/25 bg-down/15 text-down",
        amber: "border-amber/30 bg-amber/10 text-amber",
        neutral: "border-line bg-panel2 text-muted",
      },
    },
    defaultVariants: {
      tone: "neutral",
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

export { Badge, badgeVariants };
