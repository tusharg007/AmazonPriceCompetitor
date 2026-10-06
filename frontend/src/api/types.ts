import type { components } from "./schema";

export type Product = components["schemas"]["ProductResponse"];
export type Observation = components["schemas"]["ProductObservationRead"];
export type Job = components["schemas"]["CollectionJobRead"];
export type Match = components["schemas"]["CompetitorRead"];
export type Evidence = components["schemas"]["EvidenceArtifactRead"];
export type Analysis = components["schemas"]["AnalysisResponse"];
export type ProductInput = components["schemas"]["ProductCreate"];
export type Page<T> = {
  items: T[];
  total: number;
  page: number;
  limit: number;
};
export type Progress = Pick<
  Job,
  "status" | "progress" | "error_code" | "error_message"
>;
