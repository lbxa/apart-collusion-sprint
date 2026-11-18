import * as React from "react"
import { cn } from "cn"
import { Separator as SeparatorPrimitive } from "radix-ui"

function Separator({
  className,
  orientation = "horizontal",
  decorative = true,
  tone = "muted",
  ...props
}: React.ComponentProps<typeof SeparatorPrimitive.Root> & { tone?: "muted" | "ink" }) {
  return (
    <SeparatorPrimitive.Root
      data-slot="separator"
      decorative={decorative}
      orientation={orientation}
      className={cn(
        "shrink-0 data-horizontal:h-px data-horizontal:w-full data-vertical:w-px data-vertical:self-stretch",
        tone === "ink" ? "bg-foreground" : "bg-border",
        className
      )}
      {...props}
    />
  )
}

export { Separator }
