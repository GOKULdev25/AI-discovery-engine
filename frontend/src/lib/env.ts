/**
 * The one module in the frontend allowed to read `process.env` (IP§0.1
 * rule 3 / EV-INV-03's frontend counterpart). Every other module imports
 * from here instead.
 */
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
