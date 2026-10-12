export function userFacingDataError(error, fallback) {
  const message = String(error?.message ?? error ?? "").trim();
  if (/jwt.*(issued|iat).*future|issued at.*future/i.test(message)) {
    return (
      "Your computer clock is out of sync, so Supabase cannot verify your "
      + "session. Sync Windows time, restart the dashboard, and sign in again. "
      + "Your saved data has not been deleted."
    );
  }
  return message || fallback;
}
