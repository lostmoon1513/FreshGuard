import { useEffect, useState } from "react";
import { getFreshGuardStatus } from "../api.js";

const REFRESH_MS = 15000;

/** Header pill showing whether the FreshGuard SDK is connected (mock or real). */
export default function StatusPill() {
  const [status, setStatus] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      getFreshGuardStatus()
        .then((s) => !cancelled && setStatus(s))
        .catch(() => !cancelled && setStatus({ mode: "unknown", reachable: false }));
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  if (!status) return null;

  let color = "green";
  let text = status.mode === "mock" ? "FreshGuard: mock" : "FreshGuard: connected";
  if (!status.reachable) {
    color = "red";
    text = status.mode === "unknown" ? "Backend unreachable" : "FreshGuard: unreachable";
  } else if (status.authenticated === false) {
    color = "amber";
    text = "FreshGuard: bad API key";
  } else if (status.mode === "mock") {
    color = "grey";
  }

  const detail = [status.error, status.base_url, status.sdk_version && `SDK ${status.sdk_version}`]
    .filter(Boolean)
    .join(" · ");

  return (
    <span className={`badge badge-${color} status-pill`} title={detail || undefined}>
      <span className="dot" aria-hidden />
      {text}
    </span>
  );
}
