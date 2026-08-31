import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const allowedUrl = /^(?:https?:\/\/|mailto:)/i;

function transformUrl(url: string): string {
  return allowedUrl.test(url) ? url : "";
}

export function MarkdownContent({ content }: { content: string }) {
  return <div className="markdown-content">
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      urlTransform={transformUrl}
      components={{
        a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noreferrer" />
      }}
    >
      {content}
    </ReactMarkdown>
  </div>;
}
