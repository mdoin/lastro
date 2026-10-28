// SPDX-License-Identifier: AGPL-3.0-or-later
/** Central de notificações internas: alertas do Radar cripto, reuniões extraordinárias e vereditos. Sem serviço externo. */
import { Link } from "react-router-dom";
import { getNotifications, readAllNotifications, readNotification } from "../api/crypto";
import { Icon } from "../components/Icon";
import { Badge, EmptyState, ErrorNotice, Loading, PageHeader } from "../components/ui";
import { useApp } from "../lib/appContext";
import { formatDateTime } from "../lib/dates";
import { useAsync } from "../lib/useAsync";
import "../styles/crypto.css";

const TONE: Record<string, "critical" | "warning" | "neutral" | "good"> = { conselho: "critical", risco: "warning", atencao: "neutral", info: "good" };
const KIND: Record<string, string> = {
  cripto_alerta: "Alerta do Radar cripto", cripto_reuniao: "Reunião extraordinária", reuniao_concluida: "Veredito disponível",
};

export function NotificationsPage() {
  const q = useAsync(getNotifications, []);
  const { refresh } = useApp();
  const read = async (id: string) => { await readNotification(id); await q.reload(); void refresh(); };
  return (
    <div className="stack-lg">
      <PageHeader eyebrow="Sistema" title="Notificações"
        lede="Avisos do Radar cripto e das reuniões que o Conselho fez sozinho. Ficam só aqui no Lastro; nenhum serviço externo é usado."
        actions={q.data?.unread ? <button type="button" className="btn btn-ghost btn-sm" onClick={() => void readAllNotifications().then(q.reload).then(refresh)}>Marcar todas como lidas</button> : undefined} />
      {q.loading && !q.data && <Loading />}
      <ErrorNotice error={q.error} onRetry={q.reload} />
      {q.data && !q.data.items.length && <EmptyState title="Nada por aqui" icon="inbox">Quando o Radar detectar algo relevante ou o Conselho se reunir, você verá aqui.</EmptyState>}
      <ul className="notif-list">
        {(q.data?.items ?? []).map((n) => (
          <li key={n.id} className="notif" data-status={n.status}>
            <span className="notif-icon" aria-hidden="true"><Icon name={n.kind === "cripto_reuniao" ? "layers" : n.kind === "reuniao_concluida" ? "check" : "pulse"} /></span>
            <div className="notif-main">
              <p className="notif-title">
                {n.status === "novo" && <span className="visually-hidden">Não lida: </span>}
                <strong>{n.title}</strong> <Badge tone={TONE[n.severity] ?? "neutral"}>{KIND[n.kind] ?? n.kind}</Badge>
              </p>
              <p className="small">{n.body}</p>
              <p className="tiny muted">{formatDateTime(n.created_at)}</p>
            </div>
            <div className="notif-actions">
              {n.link && <Link className="btn btn-secondary btn-sm" to={n.link} onClick={() => void read(n.id)}>
                {n.kind === "cripto_reuniao" ? "Acompanhar reunião" : n.kind === "reuniao_concluida" ? "Ver veredito" : "Ver no Radar"}</Link>}
              {n.status === "novo" && <button type="button" className="btn btn-ghost btn-sm" onClick={() => void read(n.id)}>Marcar como lida</button>}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
