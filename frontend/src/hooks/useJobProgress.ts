import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { socketURL } from "../api/client";
import { active } from "../api/queries";
import type { Progress } from "../api/types";

export function useJobProgress(id: string | null) {
  const [frame, setFrame] = useState<{ id: string; progress: Progress } | null>(
    null,
  );
  const client = useQueryClient();
  useEffect(() => {
    if (!id) return;
    let socket: WebSocket;
    try {
      socket = new WebSocket(socketURL(id));
    } catch {
      return; // The job query continues polling when sockets are unavailable.
    }
    socket.onmessage = (event) => {
      try {
        const progress = JSON.parse(event.data) as Progress;
        if (
          ![
            "queued",
            "running",
            "succeeded",
            "partial",
            "failed",
            "cancelled",
          ].includes(progress.status) ||
          typeof progress.progress !== "number" ||
          !Number.isFinite(progress.progress) ||
          progress.progress < 0 ||
          progress.progress > 100
        )
          return;
        setFrame({ id, progress });
        if (!active(progress.status)) {
          void client.invalidateQueries();
          socket.close();
        }
      } catch {
        /* HTTP polling remains available if a frame cannot be read. */
      }
    };
    return () => socket.close();
  }, [id, client]);
  return frame?.id === id ? frame.progress : null;
}
