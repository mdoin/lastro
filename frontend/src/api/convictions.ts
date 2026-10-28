// SPDX-License-Identifier: AGPL-3.0-or-later
/** Convicções: previsões dos agentes no Conselho, conferidas depois, e a calibração de cada um. */
import { api } from "./client";

export type PredictionStatus = "aberta" | "aconteceu" | "nao_aconteceu" | "anulada" | "indeterminada";

export interface Prediction {
  id: string;
  agent_id: string;
  conversation_id: string | null;
  message_id: string;
  statement: string;
  /** Fração em texto ("0.70"). */
  probability: string;
  due_on: string;
  check: { kind: "serie"; series_id: string; op: string; value: string } | { kind: "cripto"; symbol: string; op: string; value: string } | null;
  status: PredictionStatus;
  observed: { value: string; reference_date: string; unit: string; label: string; source: string } | null;
  resolved_by: "dados" | "pessoa" | null;
  resolved_at: string | null;
  note: string | null;
  brier: string | null;
  created_at: string;
}

export interface Calibration {
  resolved: number;
  open: number;
  indeterminate: number;
  small_sample: boolean;
  baseline: string;
  brier: string | null;
  hits: number;
  mean_probability: string | null;
  observed_rate: string | null;
  buckets: { from: number; to: number; n: number; mean_probability: string; observed_rate: string }[];
}

export const getConvictions = () =>
  api.get<{ agents: Record<string, Calibration>; predictions: Prediction[]; today: string }>("/api/convictions");
export const resolvePrediction = (id: string, outcome: "aconteceu" | "nao_aconteceu" | "anulada", note = "") =>
  api.post<Prediction>(`/api/convictions/${encodeURIComponent(id)}/resolve`, { outcome, note });
