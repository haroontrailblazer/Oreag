export type WebhookEvent = { id: string; type: string; created_at: string; project_id: string; data: Record<string, unknown> };
export function verifyWebhook(body: Uint8Array | string, headers: Headers | Record<string, string | undefined>, secret: string, options?: { toleranceSeconds?: number; now?: number }): WebhookEvent;
