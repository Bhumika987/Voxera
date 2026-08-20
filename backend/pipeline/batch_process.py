"""
Step 5 — process every call in data/audio + data/metadata.

Runs up to MAX_CONCURRENCY calls at once (each call transcribes its agent and
customer channels concurrently too, via process_one_call_async — so at the
default MAX_CONCURRENCY=5 there are up to 10 AssemblyAI requests in flight at
a time). Already-processed calls are skipped cheaply (a DB lookup, no
transcription) so re-running this after a partial run or a crash just picks
up where it left off. Failures are logged to data/errors.log and do not stop
the rest of the batch.

Run directly:
    venv\\Scripts\\python.exe backend\\pipeline\\batch_process.py
    venv\\Scripts\\python.exe backend\\pipeline\\batch_process.py --limit 10      # quick test on the first 10
    venv\\Scripts\\python.exe backend\\pipeline\\batch_process.py --concurrency 5
"""

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from tqdm import tqdm  # noqa: E402

from process_one_call import CallProcessingError, process_one_call_async  # noqa: E402
from app.database.schema import init_db  # noqa: E402

PROJECT_ROOT = BACKEND_ROOT.parent
AUDIO_DIR = PROJECT_ROOT / "data" / "audio"
METADATA_DIR = PROJECT_ROOT / "data" / "metadata"
ERROR_LOG_PATH = PROJECT_ROOT / "data" / "errors.log"

DEFAULT_CONCURRENCY = 5

logging.basicConfig(
    filename=ERROR_LOG_PATH,
    level=logging.ERROR,
    format="%(asctime)s %(message)s",
)
logger = logging.getLogger("batch_process")


def discover_call_pairs(limit: int | None = None) -> list[tuple[Path, Path]]:
    """Every (mp3, json) pair in data/audio + data/metadata that share a call id."""
    pairs = []
    for audio_path in sorted(AUDIO_DIR.glob("*.mp3")):
        metadata_path = METADATA_DIR / f"{audio_path.stem}.json"
        if metadata_path.exists():
            pairs.append((audio_path, metadata_path))
        else:
            logger.error(f"{audio_path.stem}: no matching metadata file, skipped")
    if limit is not None:
        pairs = pairs[:limit]
    return pairs


async def run_batch(pairs: list[tuple[Path, Path]], concurrency: int) -> tuple[int, int]:
    semaphore = asyncio.Semaphore(concurrency)
    succeeded = 0
    failed = 0
    progress = tqdm(total=len(pairs), unit="call")

    async def _worker(audio_path: Path, metadata_path: Path):
        nonlocal succeeded, failed
        async with semaphore:
            try:
                await process_one_call_async(audio_path, metadata_path)
                succeeded += 1
            except CallProcessingError as e:
                failed += 1
                logger.error(f"{audio_path.stem}: {e}")
            except Exception as e:  # noqa: BLE001 - never let one bad call kill the batch
                failed += 1
                logger.error(f"{audio_path.stem}: unexpected error: {e!r}")
            finally:
                progress.update(1)
                progress.set_postfix(ok=succeeded, failed=failed)

    await asyncio.gather(*(_worker(a, m) for a, m in pairs))
    progress.close()
    return succeeded, failed


def _main() -> None:
    parser = argparse.ArgumentParser(description="Process every call recording into the database.")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="Calls to process at once.")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N calls (for a quick test).")
    args = parser.parse_args()

    init_db()
    pairs = discover_call_pairs(limit=args.limit)
    print(f"Found {len(pairs)} calls to check (already-processed ones will be skipped instantly).")
    print(f"Concurrency: {args.concurrency} calls at a time. Errors go to {ERROR_LOG_PATH}")

    start = time.time()
    succeeded, failed = asyncio.run(run_batch(pairs, args.concurrency))
    elapsed_minutes = (time.time() - start) / 60

    print(f"\nTotal processed: {succeeded}")
    print(f"Errors: {failed}")
    print(f"Time taken: {elapsed_minutes:.1f} minutes")
    if failed:
        print(f"See {ERROR_LOG_PATH} for details on failures.")


if __name__ == "__main__":
    _main()
