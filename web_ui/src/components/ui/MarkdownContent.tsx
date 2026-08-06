import type { ReactNode } from "react";

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\(https?:\/\/[^)\s]+\)|\*[^*]+\*)/g;

function inlineMarkdown(value: string): ReactNode[] {
  return value.split(INLINE).filter(Boolean).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index} className="font-semibold text-fg">{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={index} className="rounded bg-bg-3 px-1 py-0.5 font-mono text-[0.92em] text-fg">{part.slice(1, -1)}</code>;
    }
    const link = /^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/.exec(part);
    if (link) {
      return <a key={index} href={link[2]} target="_blank" rel="noreferrer" className="text-[rgb(var(--page-accent-rgb))] underline underline-offset-2">{link[1]}</a>;
    }
    if (part.startsWith("*") && part.endsWith("*")) {
      return <em key={index} className="italic">{part.slice(1, -1)}</em>;
    }
    return part;
  });
}

export function MarkdownContent({ children, className = "" }: { children: string; className?: string }) {
  const lines = children.replace(/\r\n?/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) {
      index += 1;
      continue;
    }
    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      const classes = level === 1 ? "text-[14px]" : level === 2 ? "text-[13px]" : "text-[12px]";
      const Tag = (`h${level}` as "h1" | "h2" | "h3");
      blocks.push(<Tag key={index} className={`mb-1.5 mt-3 font-semibold text-fg first:mt-0 ${classes}`}>{inlineMarkdown(heading[2])}</Tag>);
      index += 1;
      continue;
    }
    if (/^[-*]\s+/.test(line) || /^\d+\.\s+/.test(line)) {
      const ordered = /^\d+\.\s+/.test(line);
      const items: ReactNode[] = [];
      while (index < lines.length) {
        const current = lines[index].trim();
        const match = ordered ? /^\d+\.\s+(.+)$/.exec(current) : /^[-*]\s+(.+)$/.exec(current);
        if (!match) break;
        items.push(<li key={index} className="pl-0.5">{inlineMarkdown(match[1])}</li>);
        index += 1;
      }
      const Tag = ordered ? "ol" : "ul";
      blocks.push(<Tag key={`list-${index}`} className={`my-1.5 space-y-1 pl-4 ${ordered ? "list-decimal" : "list-disc"}`}>{items}</Tag>);
      continue;
    }
    if (line === "---" || line === "***") {
      blocks.push(<hr key={index} className="my-3 border-line-1" />);
    } else if (line.startsWith("> ")) {
      blocks.push(<blockquote key={index} className="my-2 border-l-2 border-line-2 pl-3 text-fg-dim">{inlineMarkdown(line.slice(2))}</blockquote>);
    } else {
      blocks.push(<p key={index} className="my-1.5 first:mt-0 last:mb-0">{inlineMarkdown(line)}</p>);
    }
    index += 1;
  }

  return <div className={className}>{blocks}</div>;
}
