import type { VariantProps } from "class-variance-authority";
import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type ResearchLink = {
  label: string;
  href: string;
  download?: boolean;
};

type Props = {
  links: ResearchLink[];
  variant?: VariantProps<typeof buttonVariants>["variant"];
  size?: VariantProps<typeof buttonVariants>["size"];
};

export default function ResearchLinks({ links, variant = "outline", size = "default" }: Props) {
  return (
    <>
      {links.map(({ href, label, download }) => {
        const external = href.startsWith("https:") || href.endsWith(".pdf");
        return (
          <Button
            key={href}
            asChild
            variant={variant}
            size={size}
            className={cn(variant === "link" && "px-0")}
          >
            <a
              href={href}
              download={download}
              target={external ? "_blank" : undefined}
              rel={external ? "noopener noreferrer" : undefined}
            >
              {label}
            </a>
          </Button>
        );
      })}
    </>
  );
}
