# Invented sample session: photo upload pipeline for a recipe-sharing app

All names, services and details below are fictional and written for this benchmark.

## Turn 1

**User:** We are building the photo upload pipeline for Crumbly, a recipe-sharing web app. The backend is a FastAPI service called recipe_api running in Docker, with Postgres as the main database. Users upload one to ten photos per recipe from their phones. Right now the upload endpoint accepts the multipart form, resizes every image into three thumbnail sizes with Pillow inside the request handler, and then writes the bytes into a Postgres bytea column on the recipe_photos table. It works on my laptop, but on the staging box uploads of more than three photos regularly hit the 30 second gateway timeout, and the recipe_photos table has grown to 14 GB after two weeks of beta traffic. What should we change first?

**Assistant:** There are two separate problems here and they have different fixes.

First, the timeout. Thumbnailing inside the request handler means the HTTP request lives as long as Pillow takes to decode, resize and re-encode every photo, three times each. Phone photos are often 4000x3000 pixels, so a ten-photo upload is thirty resize operations on the request path. The usual fix is to accept the original upload quickly, store it, return a 202 Accepted with a job id, and move thumbnail generation into a background worker. For a FastAPI service the common options are FastAPI BackgroundTasks, Celery with Redis, RQ, or Dramatiq. BackgroundTasks runs in the same process as recipe_api, so a burst of uploads still competes with request handling for CPU, and the work is lost if the container restarts. I would avoid it for image work.

Second, storage. Storing image bytes in a Postgres bytea column makes the database carry the full weight of every photo: backups get slower, replication lag grows, and VACUUM has more to do. The common pattern is to put the binary objects in S3-compatible object storage (for example MinIO for self-hosting, or a managed bucket) and keep only the object key, content type, size and dimensions in Postgres.

So the first change I would make is: originals go to object storage, the recipe_photos row stores the key, and a worker generates thumbnails asynchronously.

**User:** We tried BackgroundTasks last week, actually. It fixed the timeout on staging, but when we redeployed during a load test we lost about forty thumbnail jobs, which left recipes with broken image placeholders. So I agree, BackgroundTasks is out. Let's use Celery with Redis as the broker since we already run Redis for sessions. For storage we'll use MinIO in Docker for now. Can you sketch the upload endpoint?

## Turn 2

**Assistant:** Here is a first version of the upload endpoint. It streams each file to MinIO, records a row per photo with status pending, and enqueues one Celery task per photo.

```python
from fastapi import FastAPI, UploadFile, HTTPException
from uuid import uuid4

app = FastAPI()

MAX_PHOTOS = 10
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}


@app.post("/recipes/{recipe_id}/photos", status_code=202)
async def upload_photos(recipe_id: int, files: list[UploadFile]) -> dict:
    if len(files) > MAX_PHOTOS:
        raise HTTPException(status_code=413, detail="too many photos")
    job_ids = []
    for file in files:
        if file.content_type not in ALLOWED_TYPES:
            raise HTTPException(status_code=415, detail="unsupported type")
        key = f"originals/{recipe_id}/{uuid4()}"
        await storage.put_object(key, file.file, content_type=file.content_type)
        photo_id = await db.insert_photo(recipe_id=recipe_id, key=key, status="pending")
        job_ids.append(make_thumbnails.delay(photo_id, key).id)
    return {"photo_jobs": job_ids}
```

The Celery task downloads the original from MinIO, produces the three sizes, uploads them next to the original, and marks the row ready:

```python
from celery import Celery
from PIL import Image
import io

celery_app = Celery("crumbly", broker="redis://redis:6379/0")

SIZES = {"small": 320, "medium": 800, "large": 1600}


@celery_app.task(bind=True, max_retries=3, acks_late=True)
def make_thumbnails(self, photo_id: int, key: str) -> list[str]:
    original = storage.get_object_bytes(key)
    image = Image.open(io.BytesIO(original))
    image.load()
    written = []
    for name, width in SIZES.items():
        copy = image.copy()
        copy.thumbnail((width, width))
        buffer = io.BytesIO()
        copy.save(buffer, format="WEBP", quality=82)
        thumb_key = key.replace("originals/", f"thumbs/{name}/")
        storage.put_object_bytes(thumb_key, buffer.getvalue(), content_type="image/webp")
        written.append(thumb_key)
    db.mark_photo_ready(photo_id, thumbnails=written)
    return written
```

Note `acks_late=True`: the task is acknowledged only after it finishes, so if a worker container is killed mid-job, Redis hands the job to another worker instead of dropping it. That is the property BackgroundTasks did not give you.

For the frontend, the client now gets job ids back immediately. The simplest way to show progress is for the browser to poll a status endpoint every second until each photo is ready.

**User:** The endpoint works and uploads now return in under a second. Two follow-ups. One, we tried the polling approach and with about two hundred concurrent beta users the status endpoint became the busiest route we have, hammering Postgres with tiny queries; our database CPU doubled. Two, a few users uploaded HEIC photos from iPhones and they all failed with unsupported type. What would you do?

## Turn 3

**Assistant:** For progress updates, replace polling with push. Two reasonable choices: WebSockets or Server-Sent Events. Here the traffic is one-way (server tells the browser a photo is ready), so Server-Sent Events are simpler: plain HTTP, automatic reconnect in the browser, and no extra protocol upgrade handling in your proxy. The Celery task publishes a small message on a Redis pub/sub channel when it finishes, and an SSE endpoint in recipe_api subscribes to the channel for that recipe and forwards events to the browser. Postgres is no longer touched for progress at all.

```python
from fastapi.responses import StreamingResponse


async def photo_events(recipe_id: int):
    channel = f"recipe:{recipe_id}:photos"
    async with redis.pubsub() as pubsub:
        await pubsub.subscribe(channel)
        async for message in pubsub.listen():
            if message["type"] == "message":
                yield f"data: {message['data'].decode()}\n\n"


@app.get("/recipes/{recipe_id}/photos/events")
async def stream_photo_events(recipe_id: int) -> StreamingResponse:
    return StreamingResponse(photo_events(recipe_id), media_type="text/event-stream")
```

In `make_thumbnails`, after `db.mark_photo_ready`, publish the event:

```python
def publish_ready(recipe_id: int, photo_id: int, thumbnails: list[str]) -> None:
    payload = json.dumps({"photo_id": photo_id, "thumbnails": thumbnails})
    redis_sync.publish(f"recipe:{recipe_id}:photos", payload)
```

For HEIC: Pillow does not decode HEIC on its own. You could convert on the client before upload, but older browsers cannot do that reliably and it moves the problem rather than solving it. A better option is the pillow-heif plugin in the worker image, which registers a HEIC opener with Pillow. Then add "image/heic" and "image/heif" to ALLOWED_TYPES. Since thumbnails are written as WebP anyway, nothing downstream changes.

One more thing to watch: the worker currently decodes the full original into memory. A 48 megapixel phone photo can use several hundred megabytes once decoded. Call `image.draft("RGB", (1600, 1600))` for JPEGs before `load()` so Pillow decodes at reduced scale, and set a worker concurrency that fits the container memory limit.

**User:** Great. To summarise where we are: originals and thumbnails live in MinIO, Postgres keeps only keys and status, Celery with Redis does thumbnails with acks_late, progress goes over Server-Sent Events via Redis pub/sub, and HEIC goes through pillow-heif in the worker. We ruled out thumbnailing in the request handler, bytea storage, FastAPI BackgroundTasks, and status polling. Next I need to add per-user upload rate limits and a cleanup job for originals whose recipe was deleted.
