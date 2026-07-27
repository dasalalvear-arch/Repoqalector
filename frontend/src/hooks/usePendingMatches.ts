import { useEffect, useState } from "react";

import { api, Match, User } from "../services/api";

// Cuenta las solicitudes de match pendientes donde el usuario es el dueño
// del item. Alimenta el badge de alerta del Header.
export function usePendingMatches(user: User | null): number {
  const [pending, setPending] = useState(0);

  useEffect(() => {
    if (!user) {
      setPending(0);
      return;
    }
    api
      .get<Match[]>("/matches")
      .then((response) => {
        const count = response.data.filter(
          (match) => match.status === "PENDING" && match.owner_id === user.id,
        ).length;
        setPending(count);
      })
      .catch(() => setPending(0));
  }, [user]);

  return pending;
}
