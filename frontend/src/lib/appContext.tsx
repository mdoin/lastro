// SPDX-License-Identifier: AGPL-3.0-or-later
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError } from "../api/client";
import { getDiagnosis, getInbox, getStatus } from "../api/endpoints";
import type { AppStatus } from "../api/types";
import { Icon } from "../components/Icon";

interface AppContextValue {
  status: AppStatus | null;
  /** Aviso legal do motor (guidance.disclaimer). `null` enquanto não houver snapshot. */
  disclaimer: string | null;
  unreadCount: number;
  refresh: () => Promise<void>;
  setDisclaimer: (text: string) => void;
  /** Notificação curta no topo ("ilha"). Use tone "error" para falhas e "info" para avisos neutros. */
  toast: (message: string, tone?: ToastTone) => void;
}

export type ToastTone = "success" | "error" | "info";

const TOAST_ICON = { success: "check", error: "alert", info: "info" } as const;

const Ctx = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AppStatus | null>(null);
  const [disclaimer, setDisclaimerState] = useState<string | null>(null);
  const [unreadCount, setUnread] = useState(0);
  const [toastMsg, setToastMsg] = useState<{ text: string; tone: ToastTone; n: number } | null>(null);
  const toastTimer = useRef<number | undefined>(undefined);

  const refresh = useCallback(async () => {
    const [s, inbox, diag] = await Promise.allSettled([getStatus(), getInbox(), getDiagnosis()]);
    if (s.status === "fulfilled") setStatus(s.value);
    if (inbox.status === "fulfilled") setUnread(inbox.value.filter((r) => !r.read).length);
    if (diag.status === "fulfilled") setDisclaimerState(diag.value.guidance.disclaimer || null);
    else if (diag.reason instanceof ApiError && diag.reason.status === 404) setDisclaimerState(null);
  }, []);

  useEffect(() => {
    void refresh();
    const t = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, 60_000);
    return () => window.clearInterval(t);
  }, [refresh]);

  const toast = useCallback((message: string, tone: ToastTone = "success") => {
    setToastMsg((prev) => ({ text: message, tone, n: (prev?.n ?? 0) + 1 }));
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToastMsg(null), 3200);
  }, []);

  const value = useMemo<AppContextValue>(
    () => ({ status, disclaimer, unreadCount, refresh, setDisclaimer: setDisclaimerState, toast }),
    [status, disclaimer, unreadCount, refresh, toast],
  );

  return (
    <Ctx.Provider value={value}>
      {children}
      <div aria-live="polite" role="status" className="visually-hidden-container">
        {toastMsg && (
          <div className={`toast ${toastMsg.tone}`} key={toastMsg.n}>
            <span className="toast-icon" aria-hidden="true">
              <Icon name={TOAST_ICON[toastMsg.tone]} />
            </span>
            {toastMsg.text}
          </div>
        )}
      </div>
    </Ctx.Provider>
  );
}

export function useApp(): AppContextValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp fora do AppProvider");
  return v;
}
