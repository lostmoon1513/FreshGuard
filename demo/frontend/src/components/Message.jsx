import Badge from "./Badge.jsx";

export default function Message({ msg }) {
  const isUser = msg.role === "user";
  return (
    <div className={`row ${isUser ? "row-user" : "row-bot"}`}>
      <div className={`bubble ${isUser ? "bubble-user" : "bubble-bot"} ${msg.error ? "bubble-error" : ""}`}>
        <div className="text">{msg.content}</div>
        {!isUser && msg.sources?.length > 0 && (
          <div className="sources">
            Retrieved from:{" "}
            {msg.sources.map((s, i) => (
              <span key={i} className="source-chip">
                {s.title}
                {s.last_updated ? ` · ${s.last_updated}` : ""}
              </span>
            ))}
          </div>
        )}
        {!isUser && msg.messageId && <Badge messageId={msg.messageId} />}
      </div>
    </div>
  );
}
