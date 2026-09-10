import { createHmac, timingSafeEqual } from "node:crypto";

/** Pass the raw, unmodified request bytes. Parse the event only after verification. */
export function verifyWebhook(body, headers, secret, { toleranceSeconds = 300, now = Date.now() / 1000 } = {}) {
  const get = name => typeof headers.get === "function" ? headers.get(name) : headers[name.toLowerCase()];
  const timestamp = get("oreag-timestamp"), signature = get("oreag-signature");
  if (!/^\d{1,12}$/.test(timestamp ?? "") || !/^v1=[a-f0-9]{64}$/.test(signature ?? "") || Math.abs(now - Number(timestamp)) > toleranceSeconds) throw new Error("Invalid or expired webhook signature");
  const expected = createHmac("sha256", secret).update(timestamp + ".").update(body).digest();
  if (!timingSafeEqual(expected, Buffer.from(signature.slice(3), "hex"))) throw new Error("Invalid webhook signature");
  return JSON.parse(Buffer.from(body).toString("utf8"));
}
