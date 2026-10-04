// Every 4xx and 5xx answer is an ApiError rendered as {"error": {"code", "message"}}.

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export function malformed(message = 'the request body is not a valid JSON object'): ApiError {
  return new ApiError(400, 'malformed_request', message);
}

export function invalid(message: string): ApiError {
  return new ApiError(422, 'validation_failed', message);
}

export function unauthenticated(message = 'a valid bearer token is required'): ApiError {
  return new ApiError(401, 'unauthenticated', message);
}

export function forbidden(message = 'not permitted for this caller'): ApiError {
  return new ApiError(403, 'forbidden', message);
}

export function notFound(message = 'no such resource'): ApiError {
  return new ApiError(404, 'not_found', message);
}

export function conflict(code: string, message: string): ApiError {
  return new ApiError(409, code, message);
}

export function errorBody(code: string, message: string): { error: { code: string; message: string } } {
  return { error: { code, message } };
}
