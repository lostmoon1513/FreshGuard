import { useEffect, useRef, useState } from "react";
import { getSamples, sendChat } from "./api.js";
import Message from "./components/Message.jsx";
import StatusPill from "./components/StatusPill.jsx";

export default function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [conversationId, setConversationId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [samples, setSamples] = useState([]);
  const bottomRef = useRef(null);

  useEffect(() => {
    getSamples()
      .then((d) => setSamples(d.questions))
      .catch(() => {});
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function send(text) {
    const message = (text ?? input).trim();
    if (!message || loading) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", content: message }]);
    setLoading(true);
    try {
      const res = await sendChat(message, conversationId);
      setConversationId(res.conversation_id);
      setMessages((m) => [
        ...m,
        { role: "assistant", content: res.answer, sources: res.sources, messageId: res.message_id },
      ]);
    } catch (err) {
      setMessages((m) => [
        ...m,
        { role: "assistant", content: `Sorry, something went wrong: ${err.message}`, error: true },
      ]);
    } finally {
      setLoading(false);
    }
  }

  function newChat() {
    setMessages([]);
    setConversationId(null);
  }

  return (
    <div className="app">
      <header>
        <div>
          <h1>FreshGuard Demo Chatbot</h1>
          <p className="muted">Answers come instantly; a badge shows whether each answer is still current.</p>
        </div>
        <div className="header-actions">
          <StatusPill />
          <button className="ghost" onClick={newChat}>
            New chat
          </button>
        </div>
      </header>

      <main>
        {messages.length === 0 && (
          <div className="empty">
            <p>Try a question. Some knowledge-base documents are deliberately outdated.</p>
            <div className="samples">
              {samples.map((q) => (
                <button key={q} className="sample" onClick={() => send(q)}>
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <Message key={m.messageId || i} msg={m} />
        ))}
        {loading && (
          <div className="row row-bot">
            <div className="bubble bubble-bot muted">Thinking…</div>
          </div>
        )}
        <div ref={bottomRef} />
      </main>

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask something, e.g. “What is the latest stable version of Python?”"
          maxLength={2000}
          autoFocus
        />
        <button type="submit" disabled={loading || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
