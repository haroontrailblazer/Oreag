"""Set OREAG_API_KEY and OREAG_PROJECT_ID. Run python example.py [file.txt]."""
import os
import sys
from pathlib import Path
from oreag import Oreag, OreagError

try:
    with Oreag(os.environ["OREAG_API_KEY"], os.environ["OREAG_PROJECT_ID"], base_url=os.getenv("OREAG_BASE_URL", "https://oreag.onrender.com")) as client:
        if len(sys.argv) > 1:
            path = Path(sys.argv[1])
            with path.open("rb") as file:
                print(client.upload_files([(path.name, file)]))
            print("Wait for file.indexed before querying the uploaded document.")
        else:
            for event in client.stream_query("What is the return policy?"):
                if event["type"] == "token": print(event["text"], end="", flush=True)
                elif event["type"] == "done": print("\nQuery ID:", event["response"]["query_id"])
            # After collecting a user's actual rating:
            # client.feedback(query_id, "not_helpful", "The policy changed.")
except OreagError as error:
    print(error.status, str(error), "Retry-After:", error.retry_after)
