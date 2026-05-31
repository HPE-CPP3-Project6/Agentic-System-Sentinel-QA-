import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";
import { cn } from "@/lib/cn";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-1.5 whitespace-nowrap text-sm font-normal transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-primary disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default:
          "bg-primary px-4 py-1.5 text-white hover:bg-primary-hover border border-primary",
        secondary:
          "bg-surface-elevated px-4 py-1.5 text-foreground border border-border hover:bg-border/30",
        outline:
          "bg-transparent px-4 py-1.5 text-foreground border border-border hover:bg-surface-elevated",
        ghost: "px-2 py-1.5 text-foreground hover:bg-surface-elevated",
        destructive:
          "bg-danger px-4 py-1.5 text-white border border-danger hover:opacity-90",
        link: "text-primary underline-offset-2 hover:underline px-0 py-0 border-0",
      },
      size: {
        default: "h-8",
        sm: "h-7 px-3 text-xs",
        lg: "h-9 px-5",
        icon: "h-8 w-8 p-0",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";
