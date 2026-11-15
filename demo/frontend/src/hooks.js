import { useEffect, useState } from "react";
import { getBadge } from "./api.js";

const POLL_MS = 2000; // contract: poll every 2 seconds
const MAX_POLLS = 90; // stop after ~3 minutes

const unavailable = (error) => ({ state: "unavailable", color: "grey", text: "Not verified", error, claims: [] });

/** Polls /messages/{id}/badge until FreshGuard finishes (or fails). */
export function useBadge(messageId) {
  const [badge, setBadge] = useState({ state: "checking", color: "blue", text: "Checking…" });

  useEffect(() => {
    let cancelled = false;
    let timer;
    let polls = 0;

    const tick = async () => {
      polls += 1;
      try {
        const b = await getBadge(messageId);
        if (cancelled) return;
        setBadge(b);
        if (b.state === "checking") {
          if (polls < MAX_POLLS) {
            timer = setTimeout(tick, POLL_MS);
          } else {
            setBadge(unavailable("Verification is taking too long (timed out)"));
          }
        }
      } catch {
        if (cancelled) return;
        // Chat backend unreachable: say so, instead of showing nothing.
        setBadge(unavailable("Could not reach the chatbot backend"));
      }
    };
    tick();

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [messageId]);

  return badge;
}
