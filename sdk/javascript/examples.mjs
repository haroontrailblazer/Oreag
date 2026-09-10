// Run from sdk/javascript: OREAG_API_KEY=... OREAG_PROJECT_ID=... node examples.mjs
import { readFile } from "node:fs/promises";
import { OreagClient, OreagError } from "./index.js";
const client = new OreagClient({ apiKey: process.env.OREAG_API_KEY, projectId: process.env.OREAG_PROJECT_ID, baseUrl: process.env.OREAG_BASE_URL });
try {
  if (process.argv[2]) {
    const path = process.argv[2];
    console.log(await client.uploadFiles([{ name: path.split(/[\\/]/).pop(), data: new Blob([await readFile(path)]) }]));
    console.log("Wait for file.indexed before querying the uploaded document.");
  } else {
    for await (const event of client.streamQuery("What is the return policy?")) {
      if (event.type === "token") process.stdout.write(event.text);
      if (event.type === "done") console.log("\nQuery ID:", event.response.query_id);
    }
    // After collecting a user's actual rating:
    // await client.feedback(queryId, "not_helpful", "The policy changed.");
  }
} catch (error) {
  if (error instanceof OreagError) console.error(error.status, error.message, "Retry-After:", error.retryAfter);
  else throw error;
}
