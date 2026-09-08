# gateway

Request handlers, one module per resource. Every handler validates input, calls a service,
and maps errors to status codes.

## Layout

- `src/handlers/` one module per resource
- `src/logging.ts` structured request logging
