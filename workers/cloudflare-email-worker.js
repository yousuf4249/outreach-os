/**
 * Cloudflare Email Worker for Weblinx Outreach OS
 *
 * Captures inbound emails routed by Cloudflare Email Routing at the edge,
 * computes an HMAC-SHA256 signature for cryptographic verification,
 * and posts the raw RFC 822 MIME payload to the FastAPI inbound webhook.
 *
 * Environment Variables required in Cloudflare Worker settings:
 * - FASTAPI_BASE_URL: e.g. "https://outreach.weblinxsolution.com"
 * - WEBHOOK_SECRET: Shared secret key for HMAC-SHA256 signing
 * - FORWARD_FALLBACK_EMAIL: (Optional) fallback mailbox if backend is unreachable
 */

export default {
  async email(message, env, ctx) {
    try {
      const rawEmail = await new Response(message.raw).arrayBuffer();
      const timestamp = Math.floor(Date.now() / 1000).toString();
      const eventId = crypto.randomUUID();

      const secret = env.WEBHOOK_SECRET || "weblinx-inbound-secret-default";
      const key = await crypto.subtle.importKey(
        "raw",
        new TextEncoder().encode(secret),
        { name: "HMAC", hash: "SHA-256" },
        false,
        ["sign"]
      );

      // Concatenate timestamp and raw email body for signature computation
      const enc = new TextEncoder();
      const tsBytes = enc.encode(timestamp + ".");
      const signedData = new Uint8Array(tsBytes.length + rawEmail.byteLength);
      signedData.set(tsBytes, 0);
      signedData.set(new Uint8Array(rawEmail), tsBytes.length);

      const signatureBuffer = await crypto.subtle.sign("HMAC", key, signedData);
      const signatureHex = Array.from(new Uint8Array(signatureBuffer))
        .map((b) => b.toString(16).padStart(2, "0"))
        .join("");

      const webhookUrl = `${env.FASTAPI_BASE_URL || "http://127.0.0.1:8000"}/api/inbound/cloudflare`;

      const response = await fetch(webhookUrl, {
        method: "POST",
        headers: {
          "Content-Type": "message/rfc822",
          "X-Webhook-Signature": signatureHex,
          "X-Webhook-Timestamp": timestamp,
          "X-Webhook-Event-ID": eventId,
          "X-Cf-Spf": message.headers.get("x-cf-spf") || "",
          "X-Cf-Dkim": message.headers.get("x-cf-dkim") || "",
          "X-Cf-Dmarc": message.headers.get("x-cf-dmarc") || "",
          "X-Envelope-From": message.from || "",
          "X-Envelope-To": message.to || "",
        },
        body: rawEmail,
      });

      if (!response.ok) {
        console.error(`Inbound webhook returned status ${response.status}: ${await response.text()}`);
        if (env.FORWARD_FALLBACK_EMAIL) {
          console.log(`Forwarding copy to fallback email: ${env.FORWARD_FALLBACK_EMAIL}`);
          await message.forward(env.FORWARD_FALLBACK_EMAIL);
        }
      } else {
        const resJson = await response.json().catch(() => ({}));
        console.log(`Inbound email processed successfully:`, resJson);
      }
    } catch (err) {
      console.error("Error processing inbound email worker:", err);
      if (env.FORWARD_FALLBACK_EMAIL) {
        await message.forward(env.FORWARD_FALLBACK_EMAIL);
      }
    }
  },
};
